"""Live face recognition, automatic enrollment, and voice identity collection."""

from __future__ import annotations

import os
import platform
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .audio import AudioError, open_microphone
from .context import ContextError, GeminiAnalyzer, PersonContextStore, VoiceEvent, VoiceEventStore
from .models import ModelError, require_landmarker, require_models
from .pipeline import VoicePipeline
from .speech import ElevenLabsTranscriber, SpeechError, resolve_speaker
from .storage import PersonStore, StoreError
from .visual import AutoEnrollment, FrameEvidence, MouthObserver, VisualError, VisualHistory
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


def _draw(frame: np.ndarray, observations: list[Observation], store: PersonStore, status: str) -> None:
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
            frame, status[:90], (10, frame.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2,
        )


def _enroll(observations: list[Observation], engine: FaceEngine, store: PersonStore) -> tuple[str, str | None]:
    if len(observations) != 1 or observations[0].person_id is not None:
        return "Enrollment needs exactly one unknown face in view.", None
    observation = observations[0]
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
    try:
        events = VoiceEventStore(data_dir)
        context = PersonContextStore(data_dir)
    except ContextError as exc:
        raise CameraError(str(exc)) from exc
    in_wsl = "microsoft" in platform.release().lower()
    use_bridge = in_wsl and (windows_python is not None or not any(Path("/dev").glob("video*")))
    if use_bridge:
        try:
            capture = WindowsCameraSource(camera_index, Path(__file__).resolve().parent.parent, windows_python)
        except BridgeError as exc:
            raise CameraError(str(exc)) from exc
        source_description = "Windows camera bridge"
        camera_clock = "windows"
    else:
        capture = cv2.VideoCapture(camera_index)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera {camera_index}. Check its index and permissions.")
        source_description = f"camera {camera_index}"
        camera_clock = "native"

    history = VisualHistory(camera_clock)
    enrollment = AutoEnrollment()
    pipeline: VoicePipeline | None = None
    mouth: MouthObserver | None = None
    executor: ThreadPoolExecutor | None = None
    analyzer: GeminiAnalyzer | None = None
    pending = {}
    failed_people: set[str] = set()
    last_mouth_at = float("-inf")
    if os.getenv("ELEVENLABSKEY"):
        try:
            microphone = open_microphone(Path(__file__).resolve().parent.parent, windows_python, microphone_device)
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
    else:
        status = "Set ELEVENLABSKEY to enable transcription."
    if os.getenv("GEMINI_API_KEY"):
        try:
            analyzer = GeminiAnalyzer(os.environ["GEMINI_API_KEY"], os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
            executor = ThreadPoolExecutor(max_workers=1)
        except ContextError as exc:
            print(f"Gemini unavailable: {exc}", flush=True)

    def schedule(person_id: str) -> None:
        if analyzer is None or executor is None or person_id in pending or person_id in failed_people:
            return
        person_events = events.for_person(person_id)
        if person_events and context.needs_processing(person_id, person_events):
            unassigned = [event for event in events.events if event.person_id is None]
            future = executor.submit(
                analyzer.analyze, person_id, person_events, context.facts(person_id), unassigned,
            )
            pending[person_id] = (future, person_events)

    for person in store.people:
        schedule(person.id)
    print(f"Opening {source_description}. Auto-enrollment enabled; q: quit", flush=True)
    try:
        while True:
            has_frame, frame = capture.read()
            if not has_frame or frame is None:
                raise CameraError(f"Camera {camera_index} stopped returning frames.")
            captured_at = capture.capture_time if use_bridge else time.perf_counter()
            observations = engine.observe(frame, threshold)
            if enrollment.update(observations, captured_at, engine.gallery, threshold):
                enrolled_feature = observations[0].feature.copy()
                status, person_id = _enroll(observations, engine, store)
                if person_id is not None:
                    enrollment.mark_enrolled(enrolled_feature)
                    observations[0].person_id = person_id
                else:
                    enrollment.defer(captured_at)
                print(status, flush=True)
            jaw = None
            if mouth is not None and len(observations) == 1 and captured_at - last_mouth_at >= 0.1:
                jaw = mouth.score(frame, captured_at)
                last_mouth_at = captured_at
            history.add(FrameEvidence(
                captured_at, len(observations),
                observations[0].person_id if len(observations) == 1 else None, jaw,
            ))
            if pipeline is not None:
                while True:
                    try:
                        clip = pipeline.clips.get_nowait()
                    except queue.Empty:
                        break
                    person_id, reason = history.attribute(clip)
                    pipeline.submit(clip, person_id, reason)
                while True:
                    try:
                        clip, person_id, reason, transcript = pipeline.completed.get_nowait()
                    except queue.Empty:
                        break
                    person_id, reason = resolve_speaker(person_id, reason, transcript)
                    event = VoiceEvent.create(clip, transcript, person_id, reason)
                    try:
                        events.append(event)
                    except ContextError as exc:
                        status = str(exc)
                        print(status, flush=True)
                        continue
                    print(f"Transcript [{person_id or 'unassigned'}]: {transcript.text}", flush=True)
                    if person_id is not None:
                        schedule(person_id)
                while True:
                    try:
                        status = pipeline.notices.get_nowait()
                    except queue.Empty:
                        break
                    print(status, flush=True)
            for person_id, (future, analyzed_events) in list(pending.items()):
                if not future.done():
                    continue
                del pending[person_id]
                try:
                    analysis = future.result()
                    status = context.apply(person_id, analyzed_events, analysis, store)
                    print(status, flush=True)
                    schedule(person_id)
                except (ContextError, StoreError, OSError) as exc:
                    failed_people.add(person_id)
                    status = f"Gemini context unavailable: {exc}"
                    print(status, flush=True)
            _draw(frame, observations, store, status)
            cv2.imshow("Face recognition", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return
    except cv2.error as exc:
        raise CameraError(f"OpenCV camera processing failed: {exc}") from exc
    except BridgeError as exc:
        raise CameraError(str(exc)) from exc
    finally:
        if pipeline is not None:
            pipeline.close()
        if mouth is not None:
            mouth.close()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        capture.release()
        cv2.destroyAllWindows()
