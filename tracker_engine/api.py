"""FastAPI backend for MongoDB person records and their linked local files."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from mongodb.people import PNG_SIGNATURE, MongoError, Person, PersonRepository, migrate_local_people


MAX_ENROLLMENT_BYTES = 10 * 1024 * 1024


class RenamePerson(BaseModel):
    name: str


class AddNote(BaseModel):
    path: str


class PersonService:
    def __init__(self, repository: PersonRepository | None = None, data_dir: Path | None = None):
        self.repository = repository or PersonRepository.from_environment(data_dir)
        if repository is None:
            try:
                migrate_local_people(self.repository, self.repository.root)
            except Exception:
                self.repository.close()
                raise
        self.lock = threading.RLock()

    def close(self) -> None:
        self.repository.close()


def _response(person: Person) -> dict:
    return {
        "id": person.id,
        "name": person.name,
        "label": person.label,
        "facts": list(person.facts),
        "image_paths": list(person.image_paths),
        "note_paths": list(person.note_paths),
        "image_url": f"/people/{person.id}/image",
    }


def _service(request: Request) -> PersonService:
    return request.app.state.people_service


def create_app(repository: PersonRepository | None = None, data_dir: Path | None = None) -> FastAPI:
    """Create the API; file paths resolve relative to the configured data directory."""
    if repository is None:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    service = PersonService(repository, data_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="Tracker Engine API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )
    app.state.people_service = service

    @app.get("/health")
    def health():
        return {"status": "ok", "mongodb": True}

    @app.get("/people")
    def list_people(request: Request):
        current = _service(request)
        with current.lock:
            return [_response(person) for person in current.repository.list_people()]

    @app.get("/people/{person_id}")
    def get_person(person_id: str, request: Request):
        current = _service(request)
        try:
            with current.lock:
                return _response(current.repository.get(person_id))
        except MongoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/people/{person_id}/image")
    def get_person_image(person_id: str, request: Request):
        current = _service(request)
        try:
            with current.lock:
                png = current.repository.image_bytes(person_id)
        except MongoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=png, media_type="image/png")

    @app.post("/people", status_code=201)
    async def create_person(request: Request, image: UploadFile = File(...)):
        payload = await image.read(MAX_ENROLLMENT_BYTES + 1)
        if len(payload) > MAX_ENROLLMENT_BYTES:
            raise HTTPException(status_code=413, detail="Enrollment image must be at most 10 MiB.")
        if not payload.startswith(PNG_SIGNATURE):
            raise HTTPException(status_code=422, detail="Enrollment image must be a PNG.")
        current = _service(request)
        try:
            with current.lock:
                return _response(current.repository.enroll(payload))
        except MongoError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.patch("/people/{person_id}")
    def rename_person(person_id: str, change: RenamePerson, request: Request):
        current = _service(request)
        try:
            with current.lock:
                return _response(current.repository.assign_name(person_id, change.name))
        except MongoError as exc:
            status = 404 if "No enrolled person" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/people/{person_id}/notes")
    def add_note(person_id: str, note: AddNote, request: Request):
        current = _service(request)
        try:
            with current.lock:
                return _response(current.repository.add_note_path(person_id, note.path))
        except MongoError as exc:
            status = 404 if "No enrolled person" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    return app
