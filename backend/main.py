"""Unified FastAPI entry-point for the face-tracker backend.

Start the server with:
    uvicorn backend.main:app --reload

Routes:
  /people  — person enrollment, images, notes  (PeopleController)
  /graph   — knowledge graph nodes             (GraphController)
  /health  — liveness check
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend.mongodb.controllers.people_controller import (
    people_router,
    PersonService,
    set_service,
    set_post_repos,
)
from backend.graph_lib.controllers.graph_controller import (
    graph_router,
    set_graph_db,
)
from backend.mongodb.handlers.people_handler import MongoError
from backend.graph_lib.handlers.graph_db import GraphDB
from backend.mongodb.controllers.post_controller import posts_router
from backend.mongodb.controllers.image_controller import image_router

class UDPLocationProtocol(asyncio.DatagramProtocol):
    def __init__(self, broadcast_queue: asyncio.Queue):
        self.broadcast_queue = broadcast_queue

    def datagram_received(self, data, addr):
        try:
            text = data.decode('utf-8', errors='ignore').strip()
            # print(f"DEBUG UDP: {text}") # Debug log
            parts = text.split('|')
            acc_str = parts[0]
            heading = float(parts[1])
            lat, lon, alt = [float(v) for v in parts[2].split(',')]
            
            packet = {
                "accel": acc_str,
                "heading": heading,
                "lat": lat,
                "lon": lon
            }
            # Add print to verify it's pushing to queue
            print(f"[UDP] Rcvd -> {lat}, {lon} | WS Count: {len(self.broadcast_queue._queue)}", flush=True)
            
            try:
                self.broadcast_queue.put_nowait(packet)
            except asyncio.QueueFull:
                pass
        except Exception as e:
            print(f"[UDP Error] {e}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── People (MongoDB) ──────────────────────────────────────────────────
    svc: PersonService | None = None
    try:
        svc = PersonService()
        set_service(svc)
        print("✓ MongoDB (people) connected.", flush=True)
    except Exception as exc:
        print(f"✗ MongoDB (people) unavailable: {exc}", flush=True)

    # ── Posts, Notes, Pictures (MongoDB) ──────────────────────────────────
    from backend.mongodb.handlers.post_handler import PostRepository, NoteRepository, PictureRepository
    try:
        post_repo = PostRepository.from_environment()
        note_repo = NoteRepository.from_environment()
        picture_repo = PictureRepository.from_environment()
        set_post_repos(post_repo, note_repo, picture_repo)
        print("✓ MongoDB (posts/notes/pictures) connected.", flush=True)
    except Exception as exc:
        print(f"✗ MongoDB (posts/notes/pictures) unavailable: {exc}", flush=True)

    # ── Graph DB ──────────────────────────────────────────────────────────
    gdb: GraphDB | None = None
    try:
        mongo_uri = (
            os.getenv("MONGO_URI", "").strip()
            or os.getenv("MONGODB_URI", "").strip()
            or "mongodb://localhost:27017"
        )
        gdb = GraphDB(uri=mongo_uri)
        set_graph_db(gdb)
        print("✓ Graph DB connected.", flush=True)
    except Exception as exc:
        print(f"✗ Graph DB unavailable: {exc}", flush=True)

    # ── UDP Phone Stream Bridge ───────────────────────────────────────────
    broadcast_queue = asyncio.Queue(maxsize=100)
    app.state.broadcast_queue = broadcast_queue
    app.state.active_websockets = set()
    
    loop = asyncio.get_running_loop()
    transport = None
    worker_task = None
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPLocationProtocol(broadcast_queue),
            local_addr=('0.0.0.0', 5005),
            reuse_port=True
        )
        print("✓ UDP Location listener started on port 5005", flush=True)

        async def broadcast_worker():
            while True:
                packet = await broadcast_queue.get()
                disconnected = set()
                for ws in list(app.state.active_websockets):
                    try:
                        await ws.send_json(packet)
                    except Exception:
                        disconnected.add(ws)
                for ws in disconnected:
                    app.state.active_websockets.discard(ws)
                broadcast_queue.task_done()

        worker_task = asyncio.create_task(broadcast_worker())
    except Exception as exc:
        print(f"✗ UDP Location listener unavailable: {exc}", flush=True)

    yield

    if svc:
        svc.close()
    if gdb:
        gdb.close()
    if transport:
        transport.close()
    if worker_task:
        worker_task.cancel()


app = FastAPI(
    title="Face Tracker API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(people_router)
app.include_router(graph_router)
app.include_router(posts_router)
app.include_router(image_router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}

@app.websocket("/ws/location")
async def websocket_location(websocket: WebSocket):
    await websocket.accept()
    app.state.active_websockets.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        app.state.active_websockets.discard(websocket)
