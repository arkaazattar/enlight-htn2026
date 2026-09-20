"""MongoDB people controller — APIRouter for person CRUD endpoints.

Mounted in backend/main.py under /people.
"""
from __future__ import annotations

import threading
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from backend.mongodb.handlers.people_handler import (
    PNG_SIGNATURE,
    PersonRepository,
    MongoError,
    Person,
    migrate_local_people,
)


# ---------------------------------------------------------------------------
# Service (thread-safe wrapper around the repository)
# ---------------------------------------------------------------------------

class PersonService:
    def __init__(self, repository: PersonRepository | None = None) -> None:
        self.repository = repository or PersonRepository.from_environment()
        try:
            migrate_local_people(self.repository, self.repository.root)
        except Exception:
            self.repository.close()
            raise
        self.lock = threading.RLock()

    def close(self) -> None:
        self.repository.close()


_service: PersonService | None = None


def set_service(svc: PersonService) -> None:
    """Called from the lifespan in backend/main.py."""
    global _service
    _service = svc


def get_service() -> PersonService:
    if not _service:
        raise HTTPException(status_code=503, detail="Database not connected")
    return _service


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class NoteCreateRequest(BaseModel):
    content: str


class NoteUpdateRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

people_router = APIRouter(prefix="/people", tags=["People"])


@people_router.get("", response_model=list[Person])
def list_people():
    """List all enrolled people."""
    svc = get_service()
    with svc.lock:
        return list(svc.repository.list_people())


@people_router.get("/{person_id}", response_model=Person)
def get_person(person_id: str):
    """Get a specific person by ID."""
    svc = get_service()
    try:
        with svc.lock:
            return svc.repository.get(person_id)
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@people_router.get("/{person_id}/image")
def get_person_image(person_id: str):
    """Serve the person's face image as PNG."""
    svc = get_service()
    try:
        with svc.lock:
            png = svc.repository.image_bytes(person_id)
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=png, media_type="image/png")


@people_router.post("", status_code=201, response_model=Person)
async def enroll_person(file: Annotated[UploadFile, File(...)]):
    """Enroll a new person by uploading a PNG image."""
    payload = await file.read()
    if not payload.startswith(PNG_SIGNATURE):
        raise HTTPException(status_code=422, detail="Only PNG images are supported")
    svc = get_service()
    try:
        with svc.lock:
            return svc.repository.enroll(payload)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@people_router.get("/{person_id}/pictures")
def get_pictures(person_id: str):
    """Get all picture paths linked to a person."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
        return {"image_paths": person.image_paths}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@people_router.post("/{person_id}/pictures", response_model=Person)
async def add_picture(person_id: str, file: Annotated[UploadFile, File(...)]):
    """Upload a new picture and link it to the person."""
    if file.content_type != "image/png":
        raise HTTPException(status_code=400, detail="Only PNG images are supported")
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
            png_bytes = await file.read()
            image_id = uuid.uuid4().hex[:8]
            relative_path = f"faces/{person_id}_{image_id}.png"
            path = svc.repository.resolve_path(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(png_bytes)
            return svc.repository.add_image_path(person_id, relative_path)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@people_router.get("/{person_id}/notes")
def get_notes(person_id: str):
    """Get all notes linked to a person."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
        notes = []
        for note_path in person.note_paths:
            full_path = svc.repository.resolve_path(note_path)
            content = full_path.read_text(encoding="utf-8") if full_path.is_file() else ""
            notes.append({"path": note_path, "content": content})
        return {"notes": notes}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@people_router.post("/{person_id}/notes", response_model=Person)
def add_note(person_id: str, request: NoteCreateRequest):
    """Create a note file and link it to the person."""
    svc = get_service()
    try:
        with svc.lock:
            svc.repository.get(person_id)  # verify exists
            note_id = uuid.uuid4().hex[:8]
            relative_path = f"notes/{person_id}_{note_id}.txt"
            path = svc.repository.resolve_path(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(request.content, encoding="utf-8")
            return svc.repository.add_note_path(person_id, relative_path)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@people_router.put("/{person_id}/notes/{note_id}")
def edit_note(person_id: str, note_id: str, request: NoteUpdateRequest):
    """Edit an existing note by note ID (filename stem)."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
        target = next((p for p in person.note_paths if note_id in p), None)
        if not target:
            raise HTTPException(status_code=404, detail="Note not found")
        svc.repository.resolve_path(target).write_text(request.content, encoding="utf-8")
        return {"status": "ok", "path": target}
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
