"""Main camera loop — wires all subsystems together.

Run with:
    python -m tracker_engine [--camera 0] [--threshold 0.36]
"""

import dataclasses
import os
import queue
import time
from pathlib import Path

import cv2
from dotenv import load_dotenv

load_dotenv()

from .camera.display import draw
from .camera.tracker import FaceEngine, FaceTracker, MouthObserver, VisualHistory
from .llm.coordinator import GeminiCoordinator
from .memory import Memory
from .models import require_landmarker, require_models, ModelError
from .storage import PersonStore, StoreError, person_id_to_node_id
from .audio.transcriber import SpeechError, SpeechPipeline


def run(
    camera_index: int = 0,
    threshold: float = 0.36,
    model_dir: Path | None = None,
    data_dir: Path | None = None,
    mic_device: int | None = None,
) -> None:
    project_root = Path(__file__).resolve().parent.parent
    model_dir = model_dir or project_root / "models"
    data_dir = data_dir or project_root / "data"

    # ---------------------------------------------------------------
    # Initialise subsystems
    # ---------------------------------------------------------------
    memory = Memory()
    store = PersonStore(data_dir)
    engine = FaceEngine(model_dir)

    # Connect to graph DB (optional — needs MONGO_URI or defaults to localhost)
    graph_db = None
    try:
        from backend.graph_lib.handlers.graph_db import GraphDB
        mongo_uri = (
            os.getenv("MONGO_URI", "").strip()
            or os.getenv("MONGODB_URI", "").strip()
            or "mongodb://localhost:27017"
        )
        graph_db = GraphDB(uri=mongo_uri)
        print("Graph DB connected.", flush=True)
    except Exception as exc:
        print(f"Graph DB unavailable (person records remain in MongoDB): {exc}", flush=True)

    # Load existing enrolled faces into gallery + memory
    engine.gallery = store.load_gallery(engine.recognizer)
    for pid in store.person_ids:
        memory.add(pid)
        # Load name from graph DB into memory if available
        if graph_db is not None:
            try:
                node = graph_db.get_node(person_id_to_node_id(pid))
                if node and node.name:
                    memory.assign_name(pid, node.name)
            except Exception:
                pass
        memory.mark_clean(pid)

    tracker = FaceTracker()
    history = VisualHistory()

    # Open camera
    cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera {camera_index}.")

    # Mouth observer (optional — needs mediapipe)
    mouth: MouthObserver | None = None
    try:
        landmarker_path = require_landmarker(model_dir)
        mouth = MouthObserver(landmarker_path)
    except (ModelError, Exception) as exc:
        print(f"Mouth observer unavailable (speech attribution disabled): {exc}", flush=True)

    # Speech pipeline (optional — needs ELEVENLABSKEY)
    speech: SpeechPipeline | None = None
    elevenlabs_key = os.getenv("ELEVENLABSKEY")
    if elevenlabs_key:
        try:
            speech = SpeechPipeline(api_key=elevenlabs_key, device=mic_device)
            speech.start()
            dev_name = f"device {mic_device}" if mic_device is not None else "system default"
            print(f"Speech pipeline started ({dev_name}).", flush=True)
        except SpeechError as exc:
            print(f"Speech pipeline unavailable: {exc}", flush=True)

    # Gemini coordinator (optional — needs GEMINI_API_KEY)
    coordinator: GeminiCoordinator | None = None
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
    if gemini_key:
        try:
            coordinator = GeminiCoordinator(memory, store, graph_db=graph_db, api_key=gemini_key)
            coordinator.start()
            print("Gemini coordinator started.", flush=True)
        except Exception as exc:
            print(f"Gemini unavailable: {exc}", flush=True)

    status = "Running. q: quit"
    last_mouth_at = float("-inf")
    fps_ts: list[float] = []
    consecutive_empty_frames = 0

    print(f"Camera {camera_index} open. Auto-enrollment enabled. q: quit", flush=True)

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                consecutive_empty_frames += 1
                if consecutive_empty_frames > 30:
                    print("Camera stopped returning frames.", flush=True)
                    break
                time.sleep(0.01)
                continue
            consecutive_empty_frames = 0

            at = time.perf_counter()

            # ---- Face detection + recognition ----
            observations = engine.detect(frame, threshold)
            tracker.update(observations, at)

            # ---- Auto-enroll stable unknown faces ----
            for obs in observations:
                if tracker.ready_to_enroll(obs, at):
                    encoded, png = cv2.imencode(".png", obs.aligned)
                    if encoded:
                        try:
                            pid = store.enroll(png.tobytes())
                            engine.gallery[pid] = obs.feature.copy()
                            memory.add(pid)
                            tracker.mark_enrolled(obs, pid)
                            # Auto-create a graph node with the same integer ID
                            if graph_db is not None:
                                try:
                                    from backend.graph_lib.handlers.models import GraphNode
                                    graph_db.add_node(GraphNode(
                                        node_id=person_id_to_node_id(pid),
                                        name="",
                                        description="",
                                    ))
                                except Exception as gexc:
                                    print(f"Graph node create failed for {pid}: {gexc}", flush=True)
                            status = f"Enrolled new person {pid[-6:]}"
                            print(status, flush=True)
                        except StoreError as exc:
                            status = f"Enroll failed: {exc}"
                            tracker.defer_enrollment(obs)
                    else:
                        tracker.defer_enrollment(obs)

            # ---- Mouth scoring (~30 Hz) ----
            mouth_scores: dict[str, float] = {}
            if mouth is not None and at - last_mouth_at >= 0.033:
                mouth_scores = mouth.score(frame, observations, at)
                last_mouth_at = at

            # ---- Record frame evidence ----
            history.add(observations, mouth_scores, at)

            # ---- Drain speech turns from pipeline ----
            if speech is not None:
                # Drain notices
                while True:
                    try:
                        notice = speech.notices.get_nowait()
                        print(notice, flush=True)
                    except queue.Empty:
                        break

                # Drain completed turn batches
                while True:
                    try:
                        turns = speech.turns.get_nowait()
                    except queue.Empty:
                        break

                    # Attribute each turn to a person via visual history
                    attributed = []
                    for turn in turns:
                        person_id = history.attribute(turn)
                        if person_id:
                            turn = dataclasses.replace(turn, person_id=person_id)
                            label = memory.label(person_id)
                        else:
                            label = "unattributed"
                        print(f"[{label}]: {turn.text}", flush=True)
                        attributed.append(turn)
                        status = f"{label}: {turn.text[:70]}"

                    if coordinator is not None:
                        coordinator.submit(attributed)

            # ---- FPS counter ----
            fps_ts.append(at)
            fps_ts = [t for t in fps_ts if at - t <= 1.0]
            fps = float(len(fps_ts))

            # ---- Draw HUD ----
            draw(frame, observations, memory, status, fps=fps, mic_on=(speech is not None))
            cv2.imshow("tracker_engine", frame)

            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break

    finally:
        print("Shutting down...", flush=True)
        if speech is not None:
            speech.stop()
        if coordinator is not None:
            coordinator.stop()
        if mouth is not None:
            mouth.close()
        store.close()
        cap.release()
        cv2.destroyAllWindows()
