import os
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Body, Path
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from .people import PersonRepository, MongoError, Person


# Global repository instance
repository: PersonRepository | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global repository
    try:
        repository = PersonRepository.from_environment()
    except MongoError as e:
        print(f"Failed to connect to MongoDB: {e}")
    yield
    if repository:
        repository.close()


app = FastAPI(title="Face Tracker API", lifespan=lifespan)
people_router = APIRouter(prefix="/people", tags=["PeopleController"])


class NameUpdateRequest(BaseModel):
    name: str

class NoteCreateRequest(BaseModel):
    content: str

class NoteUpdateRequest(BaseModel):
    content: str


def get_repo() -> PersonRepository:
    if not repository:
        raise HTTPException(status_code=503, detail="Database not connected")
    return repository


@people_router.get("", response_model=list[Person])
def list_people():
    """List all enrolled people."""
    try:
        return get_repo().list_people()
    except MongoError as e:
        raise HTTPException(status_code=500, detail=str(e))


@people_router.get("/{person_id}", response_model=Person)
def get_person(person_id: str):
    """Get a specific person by ID."""
    try:
        return get_repo().get(person_id)
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@people_router.post("", response_model=Person)
async def enroll_person(file: Annotated[UploadFile, File(...)]):
    """Enroll a new person by uploading a PNG image."""
    if file.content_type != "image/png":
        raise HTTPException(status_code=400, detail="Only PNG images are supported")
    try:
        png_bytes = await file.read()
        return get_repo().enroll(png_bytes)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@people_router.patch("/{person_id}/name", response_model=Person)
def assign_name(person_id: str, request: NameUpdateRequest):
    """Assign or update a name for a person."""
    try:
        return get_repo().assign_name(person_id, request.name)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))


@people_router.get("/{person_id}/pictures")
def get_all_pictures(person_id: str):
    """Get paths to all pictures linked to a person."""
    try:
        person = get_repo().get(person_id)
        return {"image_paths": person.image_paths}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@people_router.post("/{person_id}/pictures", response_model=Person)
async def add_picture(person_id: str, file: Annotated[UploadFile, File(...)]):
    """Upload a new picture and link it to the person."""
    if file.content_type != "image/png":
        raise HTTPException(status_code=400, detail="Only PNG images are supported")
    repo = get_repo()
    try:
        # Verify person exists
        person = repo.get(person_id)
        
        png_bytes = await file.read()
        image_id = uuid.uuid4().hex[:8]
        # Use a safe prefix
        prefix = person.name if person.name else person_id
        relative_path = f"faces/{prefix}_{image_id}.png"
        
        path = repo.resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(png_bytes)
            
        return repo.add_image_path(person_id, relative_path)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@people_router.get("/{person_id}/notes")
def get_all_notes(person_id: str):
    """Get all notes linked to a person and their contents."""
    repo = get_repo()
    try:
        person = repo.get(person_id)
        notes = []
        for note_path in person.note_paths:
            full_path = repo.resolve_path(note_path)
            content = ""
            if full_path.is_file():
                content = full_path.read_text(encoding="utf-8")
            notes.append({"path": note_path, "content": content})
        return {"notes": notes}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))


@people_router.post("/{person_id}/notes", response_model=Person)
def add_note(person_id: str, request: NoteCreateRequest):
    """Create a new note and link it to the person."""
    repo = get_repo()
    try:
        # Verify person exists
        repo.get(person_id)
        
        note_id = uuid.uuid4().hex[:8]
        relative_path = f"notes/{person_id}_{note_id}.txt"
        path = repo.resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        path.write_text(request.content, encoding="utf-8")
        
        return repo.add_note_path(person_id, relative_path)
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@people_router.put("/{person_id}/notes/{note_id}")
def edit_note(person_id: str, note_id: str, request: NoteUpdateRequest):
    """Edit an existing note by its note ID (e.g. filename without .txt)."""
    repo = get_repo()
    try:
        person = repo.get(person_id)
        
        # Find the note path that matches the ID
        target_path = None
        for np in person.note_paths:
            if note_id in np:
                target_path = np
                break
                
        if not target_path:
            raise HTTPException(status_code=404, detail="Note not found")
            
        full_path = repo.resolve_path(target_path)
        full_path.write_text(request.content, encoding="utf-8")
        
        return {"status": "success", "path": target_path}
    except MongoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(people_router)
