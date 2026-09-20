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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    yield

    if svc:
        svc.close()
    if gdb:
        gdb.close()


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
