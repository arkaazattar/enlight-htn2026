"""Face tracks and conservative attribution of diarized speech turns."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from math import hypot
from pathlib import Path

import cv2
import numpy as np

from .speech import SpeechClip, SpeechTurn


class VisualError(Exception):
    """The mouth landmark model cannot run."""


def _cosine(a, b) -> float:
    left, right = np.ravel(a), np.ravel(b)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else -1.0


def _iou(a, b) -> float:
    x, y = max(float(a[0]), float(b[0])), max(float(a[1]), float(b[1]))
    right = min(float(a[0] + a[2]), float(b[0] + b[2]))
    bottom = min(float(a[1] + a[3]), float(b[1] + b[3]))
    intersection = max(0, right - x) * max(0, bottom - y)
    union = float(a[2] * a[3] + b[2] * b[3]) - intersection
    return intersection / union if union > 0 else 0.0


class AutoEnrollment:
    """One enrollment timer per track; the gallery remains the duplicate guard."""

    def __init__(self):
        self.started = self.last_seen = self.feature = None
        self.samples = 0
        self.blocked = False

    def reset(self):
        self.started = self.last_seen = self.feature = None
        self.samples = 0

    def update(self, observations, at, gallery, threshold) -> bool:
        if len(observations) != 1 or observations[0].person_id or self.blocked:
            self.reset()
            return False
        observation = observations[0]
        if min(observation.face[2:4]) < 80 or any(
            _cosine(observation.feature, saved) >= threshold * .85 for saved in gallery.values()
        ):
            self.reset()
            return False
        if self.feature is None or at - self.last_seen > .5 or _cosine(self.feature, observation.feature) < .55:
            self.started, self.samples = at, 1
        else:
            self.samples += 1
        self.feature, self.last_seen = observation.feature.copy(), at
        return at - self.started >= 3 and self.samples >= 10

    def mark_enrolled(self, _feature=None):
        self.blocked = True
        self.reset()

    def defer(self, _at=None):
        self.reset()


@dataclass
class FaceTrack:
    track_id: str
    box: np.ndarray
    feature: np.ndarray
    first_seen: float
    last_seen: float
    person_id: str | None
    samples: int = 1
    enrollment: AutoEnrollment = field(default_factory=AutoEnrollment)


class FaceTracker:
    def __init__(self):
        self.tracks: dict[str, FaceTrack] = {}
        self.serial = 0

    def update(self, observations, at: float) -> None:
        self.tracks = {key: track for key, track in self.tracks.items() if at - track.last_seen <= .5}
        edges = {}
        for index, observation in enumerate(observations):
            candidates = []
            for key, track in self.tracks.items():
                if observation.person_id and track.person_id and observation.person_id != track.person_id:
                    continue
                similarity = _cosine(observation.feature, track.feature)
                overlap = _iou(observation.face, track.box)
                center = observation.face[:2] + observation.face[2:4] / 2
                old_center = track.box[:2] + track.box[2:4] / 2
                close = np.linalg.norm(center - old_center) <= 1.5 * np.linalg.norm(track.box[2:4])
                if similarity >= .55 and (overlap > .05 or close):
                    candidates.append((.75 * similarity + .25 * overlap, key))
            edges[index] = sorted(candidates, reverse=True)
        matches = {}
        for index, candidates in edges.items():
            if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .08):
                continue
            score, key = candidates[0]
            rivals = [other[0][0] for i, other in edges.items() if i != index and other and other[0][1] == key]
            if not rivals or score - max(rivals) >= .08:
                matches[index] = key
        for index, observation in enumerate(observations):
            ambiguous = bool(edges[index]) and index not in matches
            key = matches.get(index)
            if key is None:
                self.serial += 1
                key = f"track_{self.serial}"
                self.tracks[key] = FaceTrack(
                    key, observation.face[:4].copy(), observation.feature.copy(), at, at, observation.person_id,
                )
            else:
                track = self.tracks[key]
                track.box, track.feature, track.last_seen = observation.face[:4].copy(), observation.feature.copy(), at
                track.samples += 1
                track.person_id = observation.person_id or track.person_id
            track = self.tracks[key]
            observation.track_id = key
            observation.person_id = observation.person_id or track.person_id
            observation.stable = not ambiguous and track.samples >= 3 and at - track.first_seen >= .2
            if len(observations) > 2 or any(
                _iou(observation.face, other.face) > .25 for other in observations if other is not observation
            ):
                observation.stable = False
            if not observation.stable:
                track.enrollment.reset()
        for observation in observations:
            if observation.person_id and sum(other.person_id == observation.person_id for other in observations) > 1:
                observation.stable = False
                self.tracks[observation.track_id].enrollment.reset()

    def can_enroll(self, observation, at, gallery, threshold) -> bool:
        return observation.stable and self.tracks[observation.track_id].enrollment.update(
            [observation], at, gallery, threshold,
        )

    def enrolled(self, observation, person_id):
        track = self.tracks[observation.track_id]
        track.person_id = observation.person_id = person_id
        track.enrollment.mark_enrolled()

    def defer(self, observation):
        self.tracks[observation.track_id].enrollment.defer()


def match_mouths(observations, boxes, values) -> dict[str, float]:
    """Map landmark output to face boxes, never to the detector's list order."""
    if len(boxes) != len(observations) or not 1 <= len(boxes) <= 2:
        return {}
    result = {}
    for box, value in zip(boxes, values):
        ranked = sorted(((_iou(box, obs.face), obs.track_id) for obs in observations), reverse=True)
        if not ranked or ranked[0][0] < .3 or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .1):
            return {}
        key = ranked[0][1]
        if key in result or value is None:
            return {}
        result[key] = value
    return result


def mouth_score(landmarks, blendshapes) -> float | None:
    """Combine jaw movement with inner-lip opening, normalized by mouth width."""
    jaw = next((float(item.score) for item in blendshapes if item.category_name == "jawOpen"), None)
    lip = None
    if len(landmarks) > 308:
        upper, lower = landmarks[13], landmarks[14]
        left, right = landmarks[78], landmarks[308]
        width = hypot(left.x - right.x, left.y - right.y)
        if width > 1e-6:
            lip = min(1.0, 2.0 * hypot(upper.x - lower.x, upper.y - lower.y) / width)
    if jaw is None:
        return lip
    if lip is None:
        return jaw
    return (jaw + lip) / 2.0


class MouthObserver:
    def __init__(self, model_path: Path):
        if not model_path.is_file():
            raise VisualError(f"Missing mouth landmark model: {model_path}. Run 'python -m face_app download-models'.")
        try:
            import mediapipe as mp
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=2, output_face_blendshapes=True,
            )
            self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
            self.mp = mp
        except Exception as exc:
            raise VisualError(f"Could not load mouth landmark model: {exc}") from exc
        self.last_ms = -1
        self.smoothed = {}

    def score(self, frame, observations, at) -> dict[str, float]:
        if not 1 <= len(observations) <= 2:
            self.smoothed.clear()
            return {}
        self.last_ms = max(self.last_ms + 1, int(at * 1000))
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        try:
            result = self.landmarker.detect_for_video(image, self.last_ms)
        except Exception:
            return {}
        boxes, values = [], []
        for landmarks, blendshapes in zip(result.face_landmarks, result.face_blendshapes):
            xs = [point.x * frame.shape[1] for point in landmarks]
            ys = [point.y * frame.shape[0] for point in landmarks]
            boxes.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
            values.append(mouth_score(landmarks, blendshapes))
        scores = match_mouths(observations, boxes, values)
        for key, value in scores.items():
            previous, timestamp = self.smoothed.get(key, (value, at))
            scores[key] = .65 * value + .35 * previous if at - timestamp <= .3 else value
        self.smoothed = {key: (value, at) for key, value in scores.items()}
        return scores

    def close(self):
        self.landmarker.close()


@dataclass(frozen=True)
class FaceEvidence:
    track_id: str
    person_id: str | None
    mouth: float | None
    stable: bool = True


@dataclass(frozen=True)
class FrameEvidence:
    at: float
    faces: tuple[FaceEvidence, ...]


def _voiced_at(at, intervals):
    return any(start - .04 <= at <= end + .04 for start, end in intervals)


def _mouth_motion(voiced: list[float], quiet: list[float]) -> str:
    """Judge each face against its own quiet noise, leaving borderline motion uncertain."""
    baseline = float(np.median(quiet))
    quiet_noise = float(np.percentile(quiet, 90) - np.percentile(quiet, 10))
    lift = float(np.percentile(voiced, 75)) - baseline
    motion = float(np.percentile(voiced, 90) - np.percentile(voiced, 10))
    threshold = max(.018, 1.5 * quiet_noise)
    raised = sum(value > baseline + threshold for value in voiced)
    if (
        raised >= 2 and lift >= max(.018, 1.8 * quiet_noise)
        and (motion >= max(.018, 1.25 * quiet_noise) or lift >= max(.075, 3 * quiet_noise))
    ):
        return "active"
    if (
        lift < max(.025, 1.25 * quiet_noise)
        and motion < max(.045, 1.8 * quiet_noise)
        and max(voiced) < baseline + max(.065, 2.25 * quiet_noise)
    ):
        return "inactive"
    return "uncertain"


@dataclass(frozen=True)
class ClipEvidence:
    clock_source: str
    frames: tuple[FrameEvidence, ...]

    def attribute(self, clip: SpeechClip, turn: SpeechTurn) -> SpeechTurn:
        def reject(reason):
            return replace(turn, person_id=None, attribution=reason)

        if turn.attribution != "pending visual attribution":
            return turn
        if clip.clock_source != self.clock_source:
            return reject("camera and microphone clocks differ")
        frames = [item for item in self.frames if turn.start <= item.at <= turn.end]
        if turn.end - turn.start < .35:
            return reject("speech turn too short for visual attribution")
        if len(frames) < 4 or frames[0].at - turn.start > .2 or turn.end - frames[-1].at > .2:
            return reject("insufficient synchronized video")
        if any(b.at - a.at > .25 for a, b in zip(frames, frames[1:])):
            return reject("video capture gap during speech")
        if any(not 1 <= len(frame.faces) <= 2 for frame in frames):
            return reject("no face or more than two faces")
        tracks = {face.track_id for face in frames[0].faces}
        if any({face.track_id for face in frame.faces} != tracks or any(not face.stable for face in frame.faces) for frame in frames):
            return reject("face tracking is ambiguous or changed during speech")
        active, inactive = [], []
        for key in tracks:
            identities = {face.person_id for frame in frames for face in frame.faces if face.track_id == key}
            if len(identities) != 1:
                return reject("face identity changed during speech")
            samples = [(frame.at, face.mouth) for frame in self.frames for face in frame.faces
                       if face.track_id == key and face.stable and face.mouth is not None]
            # Word timestamps delimit the turn. Per-block VAD can skip a
            # spoken syllable, so it should not discard a matching video frame.
            voiced = [value for at, value in samples if turn.start <= at <= turn.end and _voiced_at(at, turn.intervals)]
            quiet = [value for at, value in samples if
                     max(clip.start, turn.start - 1) <= at <= min(clip.end, turn.end + 1)
                     and not _voiced_at(at, clip.voiced)]
            if len(quiet) < 2:
                # In a continuous conversation the microphone may never be
                # quiet. Use nearby closed-mouth samples outside this turn.
                reference = [value for at, value in samples if
                             max(clip.start, turn.start - 1) <= at <= min(clip.end, turn.end + 1)
                             and (at < turn.start - .12 or at > turn.end + .12)]
                if len(reference) >= 5:
                    quiet = sorted(reference)[:max(2, len(reference) // 2)]
            if len(voiced) < 4:
                return reject("insufficient mouth samples during speech")
            if len(quiet) < 2:
                return reject("no quiet mouth reference near speech")
            state = _mouth_motion(voiced, quiet)
            if state == "active":
                active.append(next(iter(identities)))
            elif state == "inactive":
                inactive.append(key)
        if len(active) > 1:
            return reject("more than one face moved its mouth during speech")
        if not active:
            return reject("no face showed clear mouth movement during speech")
        if len(inactive) != len(tracks) - 1:
            return reject("another face's mouth movement is uncertain")
        if active[0] is None:
            return reject("speaking face is not enrolled yet")
        return replace(turn, person_id=active[0], attribution="one clearly active speaking face")

    def attribute_turns(self, clip, turns):
        results = [self.attribute(clip, turn) for turn in turns]
        for speaker in {turn.speaker_id for turn in results if turn.speaker_id is not None}:
            people = {turn.person_id for turn in results if turn.speaker_id == speaker and turn.person_id}
            if len(people) > 1:
                results = [replace(turn, person_id=None, attribution="speaker-to-face mapping changed within clip")
                           if turn.speaker_id == speaker else turn for turn in results]
        return tuple(results)


class VisualHistory:
    def __init__(self, clock_source):
        self.clock_source = clock_source
        self.frames = deque(maxlen=1800)

    def add(self, frame):
        self.frames.append(frame)
        while self.frames and frame.at - self.frames[0].at > 35:
            self.frames.popleft()

    def snapshot(self, clip) -> ClipEvidence:
        return ClipEvidence(self.clock_source, tuple(frame for frame in self.frames if clip.start <= frame.at <= clip.end))
