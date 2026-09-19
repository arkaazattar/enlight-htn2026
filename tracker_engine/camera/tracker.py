"""Face detection, recognition, auto-enrollment, mouth motion, and speech attribution.

Consolidates FaceEngine, FaceTracker, MouthObserver, VisualHistory from the old codebase
into one coherent module. No WSL bridge logic.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from ..audio.transcriber import SpeechTurn
from ..models import require_models


class TrackerError(Exception):
    """Face detection or mouth landmark model failed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.ravel(a), np.ravel(b)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else -1.0


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x = max(float(a[0]), float(b[0]))
    y = max(float(a[1]), float(b[1]))
    right = min(float(a[0] + a[2]), float(b[0] + b[2]))
    bottom = min(float(a[1] + a[3]), float(b[1] + b[3]))
    inter = max(0.0, right - x) * max(0.0, bottom - y)
    union = float(a[2] * a[3] + b[2] * b[3]) - inter
    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Face observation (raw detector output per frame)
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    box: np.ndarray          # [x, y, w, h, ...]
    aligned: np.ndarray      # aligned crop for display
    feature: np.ndarray      # embedding vector
    person_id: str | None = None
    track_id: str = ""
    stable: bool = False
    score: float | None = None


# ---------------------------------------------------------------------------
# FaceEngine — detection + recognition
# ---------------------------------------------------------------------------

class FaceEngine:
    """Wraps YuNet detector + SFace recognizer."""

    _MIN_FACE_SIZE = 80     # ignore tiny background noise/false positives
    _MIN_DET_SCORE = 0.88   # minimum YuNet confidence score

    def __init__(self, model_dir: Path) -> None:
        detector_path, recognizer_path = require_models(model_dir)
        try:
            self.detector = cv2.FaceDetectorYN.create(
                str(detector_path), "", (320, 320), 0.88, 0.3, 5000
            )
            self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        except cv2.error as exc:
            raise TrackerError(f"Could not load face models: {exc}") from exc
        self.gallery: dict[str, np.ndarray] = {}

    def detect(self, frame: np.ndarray, threshold: float) -> list[Observation]:
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []

        observations: list[Observation] = []
        score_candidates: list[tuple[float, int, str]] = []

        for face in faces:
            w, h = float(face[2]), float(face[3])
            det_score = float(face[-1]) if len(face) > 14 else 1.0
            if w < self._MIN_FACE_SIZE or h < self._MIN_FACE_SIZE or det_score < self._MIN_DET_SCORE:
                continue

            aligned = self.recognizer.alignCrop(frame, face)
            if aligned is None or aligned.size == 0:
                continue

            feature = self.recognizer.feature(aligned).copy()
            obs = Observation(box=face[:4].copy(), aligned=aligned, feature=feature)
            idx = len(observations)
            observations.append(obs)
            for person_id, saved in self.gallery.items():
                score = float(
                    self.recognizer.match(feature, saved, cv2.FaceRecognizerSF_FR_COSINE)
                )
                if score >= threshold:
                    score_candidates.append((score, idx, person_id))

        # Assign best unique match per face
        assigned: set[str] = set()
        for score, idx, person_id in sorted(score_candidates, reverse=True):
            obs = observations[idx]
            if obs.person_id is None and person_id not in assigned:
                obs.person_id = person_id
                obs.score = score
                assigned.add(person_id)

        return observations


# ---------------------------------------------------------------------------
# FaceTracker — tracks identity across frames with auto-enrollment timing
# ---------------------------------------------------------------------------

@dataclass
class _Track:
    track_id: str
    box: np.ndarray
    feature: np.ndarray
    person_id: str | None
    first_seen: float
    last_seen: float
    samples: int = 1
    # Enrollment timer state
    enroll_started: float | None = None
    enroll_samples: int = 0
    enroll_blocked: bool = False


class FaceTracker:
    """Tracks up to N faces across frames; manages auto-enrollment readiness."""

    _TRACK_TIMEOUT = 0.4    # seconds before dropping a lost track
    _ENROLL_WINDOW = 1.0    # seconds a new face must be stable before enrolling
    _ENROLL_MIN_SAMPLES = 5
    _MIN_FACE_PX = 85       # minimum face width/height for enrollment

    def __init__(self) -> None:
        self._tracks: dict[str, _Track] = {}
        self._serial = 0

    def update(self, observations: list[Observation], at: float) -> None:
        """Match observations to existing tracks, create new tracks as needed."""
        # Drop stale tracks
        self._tracks = {
            k: t for k, t in self._tracks.items() if at - t.last_seen <= self._TRACK_TIMEOUT
        }

        # Build match candidates
        edges: dict[int, list[tuple[float, str]]] = {i: [] for i in range(len(observations))}
        for i, obs in enumerate(observations):
            for key, track in self._tracks.items():
                if obs.person_id and track.person_id and obs.person_id != track.person_id:
                    continue
                sim = _cosine(obs.feature, track.feature)
                overlap = _iou(obs.box, track.box)
                center = obs.box[:2] + obs.box[2:4] / 2
                old_center = track.box[:2] + track.box[2:4] / 2
                close = np.linalg.norm(center - old_center) <= 1.5 * np.linalg.norm(track.box[2:4])
                if sim >= 0.55 and (overlap > 0.05 or close):
                    edges[i].append((0.75 * sim + 0.25 * overlap, key))
            edges[i].sort(reverse=True)

        # Resolve unambiguous matches
        matches: dict[int, str] = {}
        for i, candidates in edges.items():
            if not candidates:
                continue
            if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
                continue
            score, key = candidates[0]
            rivals = [other[0][0] for j, other in edges.items() if j != i and other and other[0][1] == key]
            if not rivals or score - max(rivals) >= 0.08:
                matches[i] = key

        for i, obs in enumerate(observations):
            ambiguous = bool(edges[i]) and i not in matches
            key = matches.get(i)
            if key is None:
                self._serial += 1
                key = f"t{self._serial}"
                self._tracks[key] = _Track(key, obs.box.copy(), obs.feature.copy(),
                                           obs.person_id, at, at)
            else:
                track = self._tracks[key]
                track.box = obs.box.copy()
                track.feature = obs.feature.copy()
                track.last_seen = at
                track.samples += 1
                track.person_id = obs.person_id or track.person_id

            track = self._tracks[key]
            obs.track_id = key
            obs.person_id = obs.person_id or track.person_id
            obs.stable = (
                not ambiguous
                and track.samples >= 3
                and at - track.first_seen >= 0.2
                and len(observations) <= 2
            )
            # Enrollment timer
            if obs.stable and obs.person_id is None and not track.enroll_blocked:
                w, h = float(obs.box[2]), float(obs.box[3])
                if min(w, h) >= self._MIN_FACE_PX:
                    if track.enroll_started is None:
                        track.enroll_started = at
                        track.enroll_samples = 1
                    else:
                        track.enroll_samples += 1
                else:
                    track.enroll_started = None
                    track.enroll_samples = 0
            else:
                track.enroll_started = None
                track.enroll_samples = 0

    def ready_to_enroll(self, obs: Observation, at: float) -> bool:
        track = self._tracks.get(obs.track_id)
        if track is None or track.person_id is not None or track.enroll_blocked:
            return False
        if track.enroll_started is None:
            return False
        elapsed = at - track.enroll_started
        return elapsed >= self._ENROLL_WINDOW and track.enroll_samples >= self._ENROLL_MIN_SAMPLES

    def mark_enrolled(self, obs: Observation, person_id: str) -> None:
        obs.person_id = person_id
        track = self._tracks.get(obs.track_id)
        if track:
            track.person_id = person_id
            track.enroll_blocked = False
            track.enroll_started = None

    def defer_enrollment(self, obs: Observation) -> None:
        track = self._tracks.get(obs.track_id)
        if track:
            track.enroll_blocked = True
            track.enroll_started = None


# ---------------------------------------------------------------------------
# MouthObserver — MediaPipe jawOpen blendshape scoring
# ---------------------------------------------------------------------------

class MouthObserver:
    """Scores mouth openness per face using MediaPipe FaceLandmarker."""

    def __init__(self, model_path: Path) -> None:
        if not model_path.is_file():
            raise TrackerError(
                f"Missing mouth landmark model: {model_path}. "
                "Run 'python -m tracker_engine download-models'."
            )
        try:
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=2,
                output_face_blendshapes=True,
            )
            self._lm = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        except Exception as exc:
            raise TrackerError(f"Could not load mouth model: {exc}") from exc
        self._last_ms = -1
        self._smoothed: dict[str, tuple[float, float]] = {}

    def score(self, frame: np.ndarray, observations: list[Observation], at: float) -> dict[str, float]:
        if not 1 <= len(observations) <= 2:
            self._smoothed.clear()
            return {}
        self._last_ms = max(self._last_ms + 1, int(at * 1000))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._lm.detect_for_video(image, self._last_ms)
        except Exception:
            return {}

        boxes, values = [], []
        for landmarks, blendshapes in zip(result.face_landmarks, result.face_blendshapes):
            xs = [p.x * frame.shape[1] for p in landmarks]
            ys = [p.y * frame.shape[0] for p in landmarks]
            boxes.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
            values.append(
                next((float(s.score) for s in blendshapes if s.category_name == "jawOpen"), None)
            )

        # Map landmark boxes back to observation track_ids by IOU
        scores: dict[str, float] = {}
        if len(boxes) != len(observations):
            return {}
        for box, value in zip(boxes, values):
            ranked = sorted(
                ((_iou(np.array(box), obs.box), obs.track_id) for obs in observations),
                reverse=True,
            )
            if not ranked or ranked[0][0] < 0.3:
                return {}
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.1:
                return {}
            key = ranked[0][1]
            if key in scores or value is None:
                return {}
            scores[key] = value

        # Smooth over short gaps
        smoothed: dict[str, tuple[float, float]] = {}
        for key, value in scores.items():
            prev = self._smoothed.get(key)
            if prev is not None and at - prev[1] <= 0.4:
                smoothed[key] = (0.7 * value + 0.3 * prev[0], at)
            else:
                smoothed[key] = (value, at)
        self._smoothed = smoothed
        return {k: v[0] for k, v in smoothed.items()}

    def close(self) -> None:
        try:
            self._lm.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# VisualHistory — sliding window of frame evidence for speech attribution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrameSnapshot:
    at: float
    # track_id → (person_id|None, mouth_score|None, stable)
    faces: tuple[tuple[str, str | None, float | None, bool], ...]


class VisualHistory:
    """Rolling 30-second window of face + mouth evidence for speech attribution."""

    def __init__(self) -> None:
        self._frames: deque[FrameSnapshot] = deque(maxlen=1800)

    def add(self, observations: list[Observation], mouth_scores: dict[str, float], at: float) -> None:
        self._frames.append(FrameSnapshot(
            at=at,
            faces=tuple(
                (obs.track_id, obs.person_id, mouth_scores.get(obs.track_id), obs.stable)
                for obs in observations
            ),
        ))
        # Drop frames older than 35 s
        while self._frames and at - self._frames[0].at > 35:
            self._frames.popleft()

    def attribute(self, turn: "SpeechTurn") -> str | None:
        """Return person_id of the speaker for this turn, or None if uncertain."""
        # Find frames matching turn interval
        frames = [f for f in self._frames if turn.start - 0.15 <= f.at <= turn.end + 0.15]
        if not frames:
            return None

        # Find visible persons during this turn
        candidates: dict[str, list[float]] = {}  # person_id -> list of mouth scores
        for f in frames:
            for track_id, person_id, mouth_score, stable in f.faces:
                if person_id:
                    if person_id not in candidates:
                        candidates[person_id] = []
                    if mouth_score is not None:
                        candidates[person_id].append(mouth_score)

        if not candidates:
            return None

        # Single person visible during turn: attribute to them
        if len(candidates) == 1:
            return next(iter(candidates.keys()))

        # Two or more people visible: compare mouth scores
        scored = []
        for pid, scores in candidates.items():
            mean_score = float(np.mean(scores)) if scores else 0.0
            max_score = float(np.max(scores)) if scores else 0.0
            scored.append((mean_score + 0.5 * max_score, pid))

        scored.sort(reverse=True)
        # Attribute if leader has distinct mouth motion advantage
        if len(scored) >= 2 and scored[0][0] - scored[1][0] >= 0.03:
            return scored[0][1]

        return scored[0][1] if scored else None
