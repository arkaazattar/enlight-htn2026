"""Conservative visual evidence for enrollment and speech attribution."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .speech import SpeechClip


class VisualError(Exception):
    """The mouth landmark model cannot run."""


class MouthObserver:
    def __init__(self, model_path: Path):
        if not model_path.is_file():
            raise VisualError(f"Missing mouth landmark model: {model_path}. Run 'python -m face_app download-models'.")
        try:
            import mediapipe as mp
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=1, output_face_blendshapes=True,
            )
            self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
            self.mp = mp
        except Exception as exc:
            raise VisualError(f"Could not load mouth landmark model: {exc}") from exc
        self.last_ms = -1

    def score(self, frame: np.ndarray, at: float) -> float | None:
        timestamp_ms = max(self.last_ms + 1, int(at * 1000))
        self.last_ms = timestamp_ms
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self.landmarker.detect_for_video(image, timestamp_ms)
        except Exception:
            return None
        if len(result.face_blendshapes) != 1:
            return None
        return next(
            (float(category.score) for category in result.face_blendshapes[0]
             if category.category_name == "jawOpen"), None
        )

    def close(self) -> None:
        self.landmarker.close()


@dataclass(frozen=True)
class FrameEvidence:
    at: float
    face_count: int
    person_id: str | None
    mouth: float | None


class VisualHistory:
    def __init__(self, clock_source: str):
        self.clock_source = clock_source
        self.frames: deque[FrameEvidence] = deque(maxlen=1800)

    def add(self, frame: FrameEvidence) -> None:
        self.frames.append(frame)
        while self.frames and frame.at - self.frames[0].at > 35:
            self.frames.popleft()

    def attribute(self, clip: SpeechClip) -> tuple[str | None, str]:
        if clip.clock_source != self.clock_source:
            return None, "camera and microphone clocks differ"
        if not clip.voiced:
            return None, "no speech detected"
        first, last = clip.voiced[0][0], clip.voiced[-1][1]
        frames = [item for item in self.frames if first <= item.at <= last]
        if len(frames) < 10 or frames[-1].at - frames[0].at < 0.8:
            return None, "insufficient synchronized video"
        if any(item.face_count != 1 or item.person_id is None for item in frames):
            return None, "more than one face, no face, or unenrolled face"
        identities = {item.person_id for item in frames}
        if len(identities) != 1:
            return None, "face identity changed during speech"
        samples = [item for item in self.frames if clip.start <= item.at <= clip.end and item.mouth is not None]
        voiced = [item.mouth for item in samples if first <= item.at <= last and _voiced_at(item.at, clip.voiced)]
        quiet = [item.mouth for item in samples if not _voiced_at(item.at, clip.voiced)]
        if len(voiced) < 6 or len(quiet) < 2:
            return None, "insufficient mouth or quiet samples"
        assert all(item is not None for item in voiced + quiet)
        quiet_level = float(np.median(quiet))
        if (
            max(voiced) - min(voiced) < 0.10
            or float(np.mean(voiced)) < quiet_level + 0.05
            or sum(value > quiet_level + 0.08 for value in voiced) < max(2, len(voiced) // 3)
        ):
            return None, "mouth motion did not align with speech"
        return next(iter(identities)), "one visible speaking face"


def _voiced_at(at: float, intervals: tuple[tuple[float, float], ...]) -> bool:
    return any(start - 0.04 <= at <= end + 0.04 for start, end in intervals)


class AutoEnrollment:
    def __init__(self):
        self.started: float | None = None
        self.last_seen: float | None = None
        self.feature: np.ndarray | None = None
        self.samples = 0
        self.blocked = False
        self.blocked_feature: np.ndarray | None = None
        self.absent_since: float | None = None

    def update(self, observations, at: float, gallery: dict[str, np.ndarray], threshold: float) -> bool:
        if not observations:
            if self.absent_since is None:
                self.absent_since = at
            elif at - self.absent_since >= 0.8:
                self.blocked = False
                self.blocked_feature = None
            self._reset()
            return False
        self.absent_since = None
        if self.blocked and len(observations) == 1 and observations[0].person_id is None:
            if self.blocked_feature is not None and _cosine(self.blocked_feature, observations[0].feature) < 0.25:
                self.blocked = False
                self.blocked_feature = None
        if len(observations) != 1 or observations[0].person_id is not None or self.blocked:
            self._reset()
            return False
        observation = observations[0]
        if min(observation.face[2], observation.face[3]) < 80:
            self._reset()
            return False
        # A marginal miss against an existing image must not create a duplicate.
        if any(_cosine(observation.feature, saved) >= threshold * 0.85 for saved in gallery.values()):
            self._reset()
            return False
        if self.feature is None or self.last_seen is None or at - self.last_seen > 0.5 or _cosine(self.feature, observation.feature) < 0.55:
            self.started, self.samples = at, 1
        else:
            self.samples += 1
        self.feature, self.last_seen = observation.feature.copy(), at
        return self.started is not None and at - self.started >= 3 and self.samples >= 10

    def mark_enrolled(self, feature: np.ndarray) -> None:
        self.blocked = True
        self.blocked_feature = feature.copy()
        self._reset()

    def defer(self, at: float) -> None:
        """Retry a failed save only after another stable observation interval."""
        self.started = self.last_seen = at
        self.samples = 0

    def _reset(self) -> None:
        self.started = self.last_seen = None
        self.feature = None
        self.samples = 0


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    left, right = np.ravel(a), np.ravel(b)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denom) if denom else -1.0
