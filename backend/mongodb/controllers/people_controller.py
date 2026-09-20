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
from backend.mongodb.handlers.post_handler import PostRepository, NoteRepository, PictureRepository
from backend.graph_lib.controllers.graph_controller import get_graph_db
from backend.graph_lib.handlers.models import GraphNode
from backend.mongodb.handlers.people_handler import person_id_to_node_id


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

_post_repo: PostRepository | None = None
_note_repo: NoteRepository | None = None
_picture_repo: PictureRepository | None = None

def set_post_repos(post: PostRepository, note: NoteRepository, picture: PictureRepository):
    global _post_repo, _note_repo, _picture_repo
    _post_repo = post
    _note_repo = note
    _picture_repo = picture

def get_post_repo() -> PostRepository:
    if not _post_repo:
        raise HTTPException(status_code=503, detail="Post Database not connected")
    return _post_repo

def get_note_repo() -> NoteRepository:
    if not _note_repo:
        raise HTTPException(status_code=503, detail="Note Database not connected")
    return _note_repo

def get_picture_repo() -> PictureRepository:
    if not _picture_repo:
        raise HTTPException(status_code=503, detail="Picture Database not connected")
    return _picture_repo


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class NoteCreateRequest(BaseModel):
    content: str


class NoteUpdateRequest(BaseModel):
    content: str


def _format_person(p: Person) -> dict:
    node_name = None
    node_desc = None
    gdb = get_graph_db()
    if gdb:
        try:
            nid = person_id_to_node_id(p.id)
            node = gdb.get_node(nid)
            if node:
                node_name = node.name
                node_desc = node.description
        except Exception as e:
            print(f"Error fetching graph node for {p.id}: {e}", flush=True)

    facts = [node_desc] if node_desc else []
    return {
        "id": p.id,
        "name": node_name,
        "label": node_name or "Unnamed person",
        "facts": facts,
        "context": {},
        "picture_ids": p.picture_ids,
        "note_ids": p.note_ids,
        "post_ids": p.post_ids,
        "image_url": f"/people/{p.id}/image" if p.picture_ids else ""
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

people_router = APIRouter(prefix="/people", tags=["People"])


class PersonCreateRequest(BaseModel):
    name: str
    description: str | None = None
    relationship: str | None = None
    nicknames: list[str] = []


@people_router.get("")
def list_people():
    """List all enrolled people."""
    svc = get_service()
    with svc.lock:
        return [_format_person(p) for p in svc.repository.list_people()]


@people_router.post("")
def create_person(request: PersonCreateRequest):
    """Create a new person record."""
    svc = get_service()
    with svc.lock:
        person = svc.repository.create_person()

    gdb = get_graph_db()
    if gdb:
        try:
            nid = person_id_to_node_id(person.id)
            desc_parts = []
            if request.description and request.description.strip():
                desc_parts.append(request.description.strip())
            if request.relationship and request.relationship.strip():
                desc_parts.append(f"Relationship: {request.relationship.strip()}")
            if request.nicknames:
                desc_parts.append(f"Nicknames: {', '.join(request.nicknames)}")
            description = "\n".join(desc_parts)
            gdb.add_node(
                GraphNode(
                    node_id=nid,
                    name=request.name.strip(),
                    description=description,
                )
            )
        except Exception as e:
            print(f"Graph update error on create person: {e}", flush=True)

    return _format_person(person)


@people_router.get("/{person_id}")
def get_person(person_id: str):
    """Get a specific person by ID."""
    svc = get_service()
    try:
        with svc.lock:
            p = svc.repository.get(person_id)
            return _format_person(p)
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))



@people_router.get("/{person_id}/notes")
def get_notes(person_id: str):
    """Get all notes linked to a person."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
        
        notes = []
        try:
            note_repo = get_note_repo()
            for note_id in person.note_ids:
                try:
                    note = note_repo.get(note_id)
                    content = note_repo.resolve_path(note.path).read_text(encoding="utf-8")
                    notes.append({"id": note.id, "content": content})
                except Exception:
                    notes.append({"id": note_id, "missing": True})
        except Exception:
            pass # If repo is not set up

        return {"notes": notes}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))

@people_router.get("/{person_id}/posts")
def get_person_posts(person_id: str):
    """Get all posts tagged with this person."""
    svc = get_service()
    try:
        with svc.lock:
            person = svc.repository.get(person_id)
        
        post_repo = get_post_repo()
        note_repo = get_note_repo()
        
        posts_list = []
        for post_id in person.post_ids:
            try:
                post = post_repo.get(post_id)
                
                note_content = None
                if post.note_id:
                    try:
                        note = note_repo.get(post.note_id)
                        note_path = note_repo.resolve_path(note.path)
                        note_content = note_path.read_text(encoding="utf-8") if note_path.is_file() else None
                    except MongoError:
                        pass

                picture_url = None
                if post.picture_id:
                    picture_url = f"/posts/pictures/{post.picture_id}"

                tagged_people = []
                for pid in post.person_ids:
                    try:
                        p = svc.repository.get(pid)
                        p_info = _format_person(p)
                        tagged_people.append({
                            "id": p.id,
                            "label": p_info["label"],
                            "image_url": p_info["image_url"]
                        })
                    except MongoError:
                        pass

                posts_list.append({
                    "id": post.id,
                    "created_at": post.created_at.isoformat(),
                    "note_content": note_content,
                    "picture_url": picture_url,
                    "tagged_people": tagged_people
                })
            except MongoError:
                pass

        return {"posts": posts_list}
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
    """Edit an existing note by note ID."""
    # We will implement this properly in post_handler/notes_controller
    raise HTTPException(status_code=501, detail="Not implemented")

@people_router.delete("/{person_id}/notes/{note_id}")
def delete_note(person_id: str, note_id: str):
    """Delete an existing note by note ID."""
    raise HTTPException(status_code=501, detail="Not implemented")

@people_router.delete("/{person_id}")
def delete_person(person_id: str):
    """Delete a person record."""
    svc = get_service()
    try:
        with svc.lock:
            svc.repository.delete_person(person_id)
        
        # Also delete from graph if it exists
        gdb = get_graph_db()
        if gdb:
            try:
                nid = person_id_to_node_id(person_id)
                gdb.remove_node(nid)
            except Exception as e:
                print(f"Graph update error on delete person: {e}", flush=True)

        return {"status": "ok"}
    except MongoError as e:
        raise HTTPException(status_code=404, detail=str(e))
