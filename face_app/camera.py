"""Live face recognition, automatic enrollment, and voice identity collection."""

from __future__ import annotations

import os
import platform
import queue
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .audio import AudioError, open_microphone
from .context import ContextError, GeminiAnalyzer, LegacyReplay, PersonContextStore
from .identity import IdentityCoordinator
from .models import ModelError, require_landmarker, require_models
from .pipeline import VoicePipeline
from .speech import ElevenLabsTranscriber, SpeechError
from .storage import PersonStore, StoreError
from .visual import FaceEvidence, FaceTracker, FrameEvidence, MouthObserver, VisualError, VisualHistory
from .wsl_camera import BridgeError, WindowsCameraSource


class CameraError(Exception):
    """The webcam or OpenCV processing failed."""


@dataclass
class Observation:
    face: np.ndarray
    aligned: np.ndarray
    feature: np.ndarray
    person_id: str | None = None
    score: float | None = None
    track_id: str = ""
    stable: bool = False


class FaceEngine:
    def __init__(self, model_dir: Path, store: PersonStore):
        detector_path, recognizer_path = require_models(model_dir)
        try:
            self.detector = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320), 0.9, 0.3, 5000)
            self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        except cv2.error as exc:
            raise ModelError(f"OpenCV could not load the face models: {exc}") from exc
        self.gallery: dict[str, np.ndarray] = {}
        for person in store.people:
            image = cv2.imread(str(store.image_path(person)))
            if image is None:
                raise StoreError(f"Saved face image is damaged: {store.image_path(person)}")
            try:
                self.gallery[person.id] = self.recognizer.feature(image).copy()
            except cv2.error as exc:
                raise StoreError(f"Could not extract features from {store.image_path(person)}: {exc}") from exc

    def observe(self, frame: np.ndarray, threshold: float) -> list[Observation]:
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []

        observations: list[Observation] = []
        scores: list[tuple[float, int, str]] = []
        for face in faces:
            aligned = self.recognizer.alignCrop(frame, face)
            feature = self.recognizer.feature(aligned).copy()
            observation = Observation(face, aligned, feature)
            observation_index = len(observations)
            observations.append(observation)
            for person_id, saved_feature in self.gallery.items():
                score = float(
                    self.recognizer.match(
                        feature, saved_feature, cv2.FaceRecognizerSF_FR_COSINE
                    )
                )
                if score >= threshold:
                    scores.append((score, observation_index, person_id))

        # One enrolled identity should label at most one face in a frame.
        assigned_people: set[str] = set()
        for score, observation_index, person_id in sorted(scores, reverse=True):
            observation = observations[observation_index]
            if observation.person_id is None and person_id not in assigned_people:
                observation.person_id = person_id
                observation.score = score
                assigned_people.add(person_id)
        return observations


def _draw(frame: np.ndarray, observations: list[Observation], store: PersonStore, status: str, identity_status: str = "") -> None:
    for observation in observations:
        x, y, width, height = (int(value) for value in observation.face[:4])
        label = "Unknown" if observation.person_id is None else store.get(observation.person_id).label
        color = (0, 0, 255) if observation.person_id is None else (0, 200, 0)
        cv2.rectangle(frame, (x, y), (x + width, y + height), color, 2)
        cv2.putText(
            frame, label, (max(x, 0), max(y - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2
        )
    cv2.putText(
        frame, "Auto-enrollment and naming  q: quit", (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2,
    )
    if status:
        cv2.putText(
            frame, status[:90], (10, frame.shape[0] - 36),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2,
        )
    if identity_status:
        cv2.putText(frame, identity_status[:90], (10, frame.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 255, 255), 2)


def _enroll(observation: Observation, engine: FaceEngine, store: PersonStore) -> tuple[str, str | None]:
    if not observation.stable or observation.person_id is not None:
        return "Enrollment needs a stable unknown face track.", None
    if min(observation.face[2], observation.face[3]) < 80:
        return "Move closer so the face is at least 80 pixels wide and tall.", None
    encoded, png = cv2.imencode(".png", observation.aligned)
    if not encoded:
        return "Could not encode the face image.", None
    try:
        person = store.enroll(png.tobytes())
    except (StoreError, OSError) as exc:
        return str(exc), None
    engine.gallery[person.id] = observation.feature.copy()
    return f"Enrolled {person.id}; gathering identity evidence.", person.id


def run_camera(
    camera_index: int, threshold: float, model_dir: Path, data_dir: Path,
    windows_python: Path | None = None, microphone_device: int | None = None,
) -> None:
    if not 0 <= threshold <= 1:
        raise CameraError("--threshold must be between 0 and 1.")
    store = PersonStore(data_dir)
    engine = FaceEngine(model_dir, store)
    context = legacy = None
    try:
        context = PersonContextStore(data_dir)
        legacy = LegacyReplay(data_dir, store)
    except ContextError as exc:
        print(f"Identity storage unavailable: {exc}", flush=True)
    use_bridge = "microsoft" in platform.release().lower()
    project_root = Path(__file__).resolve().parent.parent
    if use_bridge:
        try:
            capture = WindowsCameraSource(camera_index, project_root, windows_python)
        except BridgeError as exc:
            raise CameraError(str(exc)) from exc
        source_description, camera_clock = "Windows camera bridge", "windows"
    else:
        capture = cv2.VideoCapture(camera_index)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera {camera_index}. Check its index and permissions.")
        source_description, camera_clock = f"camera {camera_index}", "native"

    history, tracker = VisualHistory(camera_clock), FaceTracker()
    pipeline = mouth = coordinator = None
    last_mouth_at = float("-inf")
    status = "Set ELEVENLABSKEY to enable transcription."
    identity_status = "Gemini unavailable; new speech is kept only in memory."
    try:
        if os.getenv("ELEVENLABSKEY"):
            try:
                microphone = open_microphone(project_root, windows_python, microphone_device)
                try:
                    transcriber = ElevenLabsTranscriber(os.environ["ELEVENLABSKEY"])
                except SpeechError:
                    microphone.close()
                    raise
                pipeline = VoicePipeline(microphone, transcriber)
                status = "Listening for speech."
            except (AudioError, SpeechError) as exc:
                status = f"Voice unavailable: {exc}"
                print(status, flush=True)
            if pipeline is not None:
                try:
                    mouth = MouthObserver(require_landmarker(model_dir))
                except (VisualError, ModelError) as exc:
                    status = f"Transcribing without face attribution: {exc}"
                    print(status, flush=True)
        enterprise = os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "").strip().lower() in {"true", "1"}
        if context is not None and (enterprise or os.getenv("GEMINI_API_KEY")):
            analyzer = None
            try:
                analyzer = GeminiAnalyzer(
                    os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                    enterprise=enterprise, project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                    location=os.getenv("GOOGLE_CLOUD_LOCATION"),
                )
                coordinator = IdentityCoordinator(analyzer, context, store, legacy)
            except (ContextError, OSError) as exc:
                if analyzer is not None:
                    analyzer.close()
                identity_status = f"Gemini unavailable: {exc}"
        if coordinator is None and context is not None:
            coordinator = IdentityCoordinator(None, context, store, unavailable=identity_status)
        print(identity_status if coordinator is None else coordinator.status, flush=True)
        print(f"Opening {source_description}. Two-person auto-enrollment enabled; q: quit", flush=True)

        while True:
            has_frame, frame = capture.read()
            if not has_frame or frame is None:
                raise CameraError(f"Camera {camera_index} stopped returning frames.")
            captured_at = capture.capture_time if use_bridge else time.perf_counter()
            observations = engine.observe(frame, threshold)
            tracker.update(observations, captured_at)
            for observation in observations:
                if tracker.can_enroll(observation, captured_at, engine.gallery, threshold):
                    status, person_id = _enroll(observation, engine, store)
                    if person_id is not None:
                        tracker.enrolled(observation, person_id)
                    else:
                        tracker.defer(observation)
                    print(status, flush=True)
            mouths = {}
            if mouth is not None and captured_at - last_mouth_at >= .1:
                mouths = mouth.score(frame, observations, captured_at)
                last_mouth_at = captured_at
            history.add(FrameEvidence(captured_at, tuple(
                FaceEvidence(observation.track_id, observation.person_id, mouths.get(observation.track_id), observation.stable)
                for observation in observations
            )))
            if pipeline is not None:
                while True:
                    try:
                        clip = pipeline.clips.get_nowait()
                    except queue.Empty:
                        break
                    pipeline.submit(clip, history.snapshot(clip))
                while True:
                    try:
                        turns = pipeline.completed.get_nowait()
                    except queue.Empty:
                        break
                    for turn in turns:
                        label = store.get(turn.person_id).label if turn.person_id else "unassigned"
                        status = f"{label}: {turn.attribution}"
                        print(f"Transcript [{label}; {turn.attribution}]: {turn.text}", flush=True)
                    if coordinator is not None:
                        coordinator.submit(turns)
                while True:
                    try:
                        notice = pipeline.notices.get_nowait()
                    except queue.Empty:
                        break
                    print(notice, flush=True)
            if coordinator is not None:
                coordinator.poll()
                identity_status = coordinator.status
                while coordinator.notices:
                    print(coordinator.notices.popleft(), flush=True)
            _draw(frame, observations, store, status, identity_status)
            cv2.imshow("Face recognition", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                return
    except cv2.error as exc:
        raise CameraError(f"OpenCV camera processing failed: {exc}") from exc
    except BridgeError as exc:
        raise CameraError(str(exc)) from exc
    finally:
        try:
            if pipeline is not None:
                discarded = pipeline.close()
                if discarded:
                    print(f"Discarded {discarded} pending speech clips on exit.", flush=True)
            if coordinator is not None:
                discarded = coordinator.close()
                if discarded:
                    print(f"Discarded {discarded} speech turns awaiting Gemini on exit.", flush=True)
        finally:
            if mouth is not None:
                mouth.close()
            capture.release()
            cv2.destroyAllWindows()
