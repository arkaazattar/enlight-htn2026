"""MongoDB handlers for Notes, Pictures, and Posts."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.mongodb.handlers.people_handler import MongoError, PNG_SIGNATURE


@dataclass(frozen=True)
class Note:
    id: str
    path: str
    created_at: datetime


@dataclass(frozen=True)
class Picture:
    id: str
    path: str
    created_at: datetime


@dataclass(frozen=True)
class Post:
    id: str
    person_ids: list[str] = field(default_factory=list)
    note_id: str | None = None
    picture_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.note_id and not self.picture_id:
            raise ValueError("Post must have at least one note or picture.")


class BaseRepository:
    def __init__(self, uri: str, database: str, collection: str, data_dir: Path | None = None) -> None:
        self.root = (data_dir or Path(__file__).resolve().parent.parent.parent.parent / "data").resolve()
        try:
            from pymongo import MongoClient
            client_kwargs: dict = {"serverSelectionTimeoutMS": 5000}
            try:
                import certifi
                client_kwargs["tlsCAFile"] = certifi.where()
            except ImportError:
                pass
            self.client = MongoClient(uri, **client_kwargs)
            self.collection = self.client[database][collection]
        except Exception as exc:
            try:
                self.client.close()
            except AttributeError:
                pass
            raise MongoError(f"Could not connect to MongoDB collection {collection}: {exc}") from exc

    @classmethod
    def from_environment(cls, collection_name: str, data_dir: Path | None = None):
        uri = os.getenv("MONGO_URI", "").strip() or os.getenv("MONGODB_URI", "").strip()
        if not uri:
            raise MongoError("Set MONGO_URI in .env")
        database = os.getenv("MONGODB_DATABASE", "face_app").strip() or "face_app"
        return cls(uri, database, collection_name, data_dir)

    def resolve_path(self, value: str) -> Path:
        root = self.root.resolve()
        path = (root / value).resolve()
        if not path.is_relative_to(root):
            raise MongoError(f"File path must be inside the data directory: {value}")
        return path

    def close(self) -> None:
        self.client.close()


class NoteRepository(BaseRepository):
    @classmethod
    def from_environment(cls, data_dir: Path | None = None):
        return super().from_environment("notes", data_dir)

    def get(self, note_id: str) -> Note:
        doc = self.collection.find_one({"id": note_id})
        if not doc:
            raise MongoError(f"Note {note_id} not found.")
        return Note(id=doc["id"], path=doc["path"], created_at=doc["created_at"])

    def create(self, content: str) -> Note:
        note_id = uuid.uuid4().hex[:8]
        relative_path = f"notes/{note_id}.txt"
        path = self.resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        
        doc = {
            "id": note_id,
            "path": relative_path,
            "created_at": datetime.now(timezone.utc)
        }
        self.collection.insert_one(doc)
        return Note(**doc)


class PictureRepository(BaseRepository):
    @classmethod
    def from_environment(cls, data_dir: Path | None = None):
        return super().from_environment("pictures", data_dir)

    def get(self, picture_id: str) -> Picture:
        doc = self.collection.find_one({"id": picture_id})
        if not doc:
            raise MongoError(f"Picture {picture_id} not found.")
        return Picture(id=doc["id"], path=doc["path"], created_at=doc["created_at"])

    def create(self, png_bytes: bytes) -> Picture:
        if not png_bytes.startswith(PNG_SIGNATURE):
            raise MongoError("Image must be a PNG.")
            
        picture_id = uuid.uuid4().hex[:12]
        relative_path = f"images/{picture_id}.png"
        path = self.resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(png_bytes)
            
        doc = {
            "id": picture_id,
            "path": relative_path,
            "created_at": datetime.now(timezone.utc)
        }
        self.collection.insert_one(doc)
        return Picture(**doc)


class PostRepository(BaseRepository):
    @classmethod
    def from_environment(cls, data_dir: Path | None = None):
        return super().from_environment("posts", data_dir)

    def get(self, post_id: str) -> Post:
        doc = self.collection.find_one({"id": post_id})
        if not doc:
            raise MongoError(f"Post {post_id} not found.")
        return Post(
            id=doc["id"],
            person_ids=doc.get("person_ids", []),
            note_id=doc.get("note_id"),
            picture_id=doc.get("picture_id"),
            created_at=doc["created_at"]
        )

    def list_posts(self) -> list[Post]:
        docs = self.collection.find().sort("created_at", -1)
        return [Post(
            id=doc["id"],
            person_ids=doc.get("person_ids", []),
            note_id=doc.get("note_id"),
            picture_id=doc.get("picture_id"),
            created_at=doc["created_at"]
        ) for doc in docs]

    def create(self, person_ids: list[str] = None, note_id: str = None, picture_id: str = None) -> Post:
        if not note_id and not picture_id:
            raise MongoError("Post must have at least one note or picture.")
            
        post_id = uuid.uuid4().hex[:12]
        doc = {
            "id": post_id,
            "person_ids": person_ids or [],
            "note_id": note_id,
            "picture_id": picture_id,
            "created_at": datetime.now(timezone.utc)
        }
        self.collection.insert_one(doc)
        return Post(**doc)
