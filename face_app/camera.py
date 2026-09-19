"""Live face detection, recognition, enrollment, and manual naming."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .models import ModelError, require_models
from .storage import PersonStore, StoreError
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
        frame, "e: enroll  n: name  q: quit", (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2,
    )
    if status:
        cv2.putText(
            frame, status[:90], (10, frame.shape[0] - 12),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2,
        )


def _enroll(observations: list[Observation], engine: FaceEngine, store: PersonStore) -> str:
    if len(observations) != 1 or observations[0].person_id is not None:
        return "Enrollment needs exactly one unknown face in view."
    observation = observations[0]
    if min(observation.face[2], observation.face[3]) < 80:
        return "Move closer so the face is at least 80 pixels wide and tall."
    encoded, png = cv2.imencode(".png", observation.aligned)
    if not encoded:
        return "Could not encode the face image."
    try:
        person = store.enroll(png.tobytes())
    except (StoreError, OSError) as exc:
        return str(exc)
    engine.gallery[person.id] = observation.feature.copy()
    return f"Enrolled {person.id}. Press n to name them."


def _name(observations: list[Observation], store: PersonStore) -> str:
    if len(observations) != 1 or observations[0].person_id is None:
        return "Naming needs exactly one enrolled face in view."
    person_id = observations[0].person_id
    current = store.get(person_id)
    try:
        entered = input(f"Name for {current.label} (blank to cancel): ")
    except EOFError:
        return "Name entry canceled: terminal input is unavailable."
    if not entered.strip():
        return "Name entry canceled."
    try:
        named = store.assign_name(person_id, entered)
    except (StoreError, OSError) as exc:
        return str(exc)
    print(f"Saved {named.id} as {named.name}; image: {store.image_path(named)}")
    return f"Named {named.id}: {named.name}"


def run_camera(
    camera_index: int, threshold: float, model_dir: Path, data_dir: Path,
    windows_python: Path | None = None,
) -> None:
    if not 0 <= threshold <= 1:
        raise CameraError("--threshold must be between 0 and 1.")
    store = PersonStore(data_dir)
    engine = FaceEngine(model_dir, store)
    in_wsl = "microsoft" in platform.release().lower()
    use_bridge = in_wsl and (windows_python is not None or not any(Path("/dev").glob("video*")))
    if use_bridge:
        try:
            capture = WindowsCameraSource(camera_index, Path(__file__).resolve().parent.parent, windows_python)
        except BridgeError as exc:
            raise CameraError(str(exc)) from exc
        source_description = "Windows camera bridge"
    else:
        capture = cv2.VideoCapture(camera_index)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera {camera_index}. Check its index and permissions.")
        source_description = f"camera {camera_index}"

    status = ""
    print(f"Opening {source_description}. e: enroll, n: name, q: quit", flush=True)
    try:
        while True:
            has_frame, frame = capture.read()
            if not has_frame or frame is None:
                raise CameraError(f"Camera {camera_index} stopped returning frames.")
            observations = engine.observe(frame, threshold)
            _draw(frame, observations, store, status)
            cv2.imshow("Face recognition", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                return
            if key == ord("e"):
                status = _enroll(observations, engine, store)
                print(status)
            elif key == ord("n"):
                status = _name(observations, store)
                print(status)
    except cv2.error as exc:
        raise CameraError(f"OpenCV camera processing failed: {exc}") from exc
    except BridgeError as exc:
        raise CameraError(str(exc)) from exc
    finally:
        capture.release()
        cv2.destroyAllWindows()
