"""MongoDB person records — stores only identity (id) and file paths.

Names and facts live in Memory (in-process session) and the GraphNode
(graph DB).  MongoDB is the source of truth for:
  - stable person_id
  - image_paths  (relative paths to enrolled face PNGs)
  - note_paths   (relative paths to linked note files)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MongoError(Exception):
    """MongoDB person storage is unavailable or contains invalid data."""


@dataclass(frozen=True)
class Person:
    """A stable identity with associated note, picture, and post IDs."""

    id: str
    picture_ids: list[str]
    note_ids: list[str]
    post_ids: list[str]


def person_id_to_node_id(person_id: str) -> int:
    """Convert both legacy and current stable person IDs to graph node IDs."""
    value = person_id.removeprefix("person_")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise MongoError(f"Invalid person ID: {person_id}") from exc


def _person_from_document(document: dict) -> Person:
    person_id = document.get("person_id")
    if not isinstance(person_id, str) or not person_id:
        raise MongoError("MongoDB person document has no valid person_id.")
    
    picture_ids = document.get("picture_ids", [])
    note_ids = document.get("note_ids", [])
    post_ids = document.get("post_ids", [])
    
    for field, value in [("picture_ids", picture_ids), ("note_ids", note_ids), ("post_ids", post_ids)]:
        if not isinstance(value, list) or any(not isinstance(p, str) or not p.strip() for p in value):
            raise MongoError(f"MongoDB person {person_id} has invalid {field}; expected a list of strings.")

    return Person(
        id=person_id,
        picture_ids=list(picture_ids),
        note_ids=list(note_ids),
        post_ids=list(post_ids),
    )


class PersonRepository:
    """One MongoDB document per person; image and note contents remain on disk."""

    def __init__(
        self,
        uri: str,
        database: str,
        collection: str,
        data_dir: Path | None = None,
    ) -> None:
        self.root = (
            data_dir or Path(__file__).resolve().parent.parent.parent.parent / "data"
        ).resolve()
        try:
            from pymongo import MongoClient

            client_kwargs: dict = {"serverSelectionTimeoutMS": 5000}
            try:
                import certifi

                client_kwargs["tlsCAFile"] = certifi.where()
            except ImportError:
                pass
            self.client = MongoClient(uri, **client_kwargs)
            self.client.admin.command("ping")
            self.collection = self.client[database][collection]
            self._ensure_index([("person_id", 1)], unique=True, name="person_id_unique")
        except Exception as exc:
            try:
                self.client.close()
            except AttributeError:
                pass
            raise MongoError(f"Could not connect to MongoDB: {exc}") from exc

    @classmethod
    def from_environment(cls, data_dir: Path | None = None) -> "PersonRepository":
        uri = os.getenv("MONGO_URI", "").strip() or os.getenv("MONGODB_URI", "").strip()
        if not uri:
            raise MongoError("Set MONGO_URI in .env before running the tracker or API.")
        database = os.getenv("MONGODB_DATABASE", "face_app").strip() or "face_app"
        collection = os.getenv("MONGODB_COLLECTION", "people").strip() or "people"
        return cls(uri, database, collection, data_dir)

    def _ensure_index(self, keys, **options) -> None:
        expected_keys = list(keys)
        expected_options = {k: v for k, v in options.items() if k != "name"}
        for spec in self.collection.index_information().values():
            key_spec = spec.get("key", ())
            current_keys = (
                list(key_spec.items()) if hasattr(key_spec, "items") else list(key_spec)
            )
            if current_keys == expected_keys and all(
                spec.get(k) == v for k, v in expected_options.items()
            ):
                return
        self.collection.create_index(keys, **options)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_people(self) -> tuple[Person, ...]:
        try:
            documents = self.collection.find({})
            return tuple(
                sorted(
                    (_person_from_document(doc) for doc in documents),
                    key=lambda p: p.id,
                )
            )
        except MongoError:
            raise
        except Exception as exc:
            raise MongoError(f"Could not load people from MongoDB: {exc}") from exc

    def get(self, person_id: str) -> Person:
        try:
            document = self.collection.find_one({"person_id": person_id})
        except Exception as exc:
            raise MongoError(f"Could not load {person_id} from MongoDB: {exc}") from exc
        if document is None:
            raise MongoError(f"No enrolled person has ID {person_id}.")
        return _person_from_document(document)

    def delete_person(self, person_id: str) -> None:
        try:
            result = self.collection.delete_one({"person_id": person_id})
            if result.deleted_count == 0:
                raise MongoError(f"No enrolled person has ID {person_id}.")
        except Exception as exc:
            raise MongoError(f"Could not delete {person_id} from MongoDB: {exc}") from exc

    def resolve_path(self, value: str) -> Path:
        root = self.root.resolve()
        path = (root / value).resolve()
        if not path.is_relative_to(root):
            raise MongoError(f"File path must be inside the data directory: {value}")
        return path

    def image_path(self, person_id: str) -> Path:
        person = self.get(person_id)
        if not person.picture_ids:
            raise MongoError(f"Person {person_id} has no picture IDs.")
        pic_id = person.picture_ids[0]
        face_path = self.resolve_path(f"faces/{pic_id}.png")
        if face_path.exists():
            return face_path
        img_path = self.resolve_path(f"images/{pic_id}.png")
        if img_path.exists():
            return img_path
        return face_path

    def image_bytes(self, person_id: str) -> bytes:
        try:
            return self.image_path(person_id).read_bytes()
        except OSError as exc:
            raise MongoError(f"Could not read face for {person_id}: {exc}") from exc

    def load_gallery(self, recognizer) -> dict[str, np.ndarray]:
        gallery: dict[str, np.ndarray] = {}
        for person in self.list_people():
            image = cv2.imdecode(
                np.frombuffer(self.image_bytes(person.id), dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if image is None:
                raise MongoError(f"Could not decode the saved face for {person.id}.")
            gallery[person.id] = recognizer.feature(image).copy()
        return gallery

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def enroll(self, png_bytes: bytes) -> Person:
        if not png_bytes.startswith(PNG_SIGNATURE):
            raise MongoError("Enrollment image must be a PNG.")
        person_id = uuid.uuid4().hex[:12]
        relative = f"faces/{person_id}.png"
        path = self.resolve_path(relative)
        now = datetime.now(timezone.utc)
        document = {
            "person_id": person_id,
            "picture_ids": [person_id],  # use person_id as the initial picture_id for the face
            "note_ids": [],
            "post_ids": [],
            "created_at": now,
            "updated_at": now,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(png_bytes)
            self.collection.insert_one(document)
        except Exception as exc:
            # Keep the image if MongoDB commits before the timeout fires.
            raise MongoError(f"Could not create {person_id}: {exc}") from exc
        return _person_from_document(document)

    def create_person(self, person_id: str | None = None) -> Person:
        if not person_id:
            person_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        document = {
            "person_id": person_id,
            "picture_ids": [],
            "note_ids": [],
            "post_ids": [],
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.collection.insert_one(document)
        except Exception as exc:
            raise MongoError(f"Could not create person {person_id}: {exc}") from exc
        return _person_from_document(document)

    def add_note_id(self, person_id: str, note_id: str) -> Person:
        if not isinstance(note_id, str) or not note_id.strip():
            raise MongoError("Note ID must be a nonempty string.")
        from pymongo import ReturnDocument

        try:
            result = self.collection.find_one_and_update(
                {"person_id": person_id},
                {
                    "$addToSet": {"note_ids": note_id},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            raise MongoError(f"Could not save note ID for {person_id}: {exc}") from exc
        if result is None:
            raise MongoError(f"No enrolled person has ID {person_id}.")
        return _person_from_document(result)

    def add_picture_id(self, person_id: str, picture_id: str) -> Person:
        if not isinstance(picture_id, str) or not picture_id.strip():
            raise MongoError("Picture ID must be a nonempty string.")
        from pymongo import ReturnDocument

        try:
            result = self.collection.find_one_and_update(
                {"person_id": person_id},
                {
                    "$addToSet": {"picture_ids": picture_id},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            raise MongoError(f"Could not save picture ID for {person_id}: {exc}") from exc
        if result is None:
            raise MongoError(f"No enrolled person has ID {person_id}.")
        return _person_from_document(result)

    def add_post_id(self, person_id: str, post_id: str) -> Person:
        if not isinstance(post_id, str) or not post_id.strip():
            raise MongoError("Post ID must be a nonempty string.")
        from pymongo import ReturnDocument

        try:
            result = self.collection.find_one_and_update(
                {"person_id": person_id},
                {
                    "$addToSet": {"post_ids": post_id},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            raise MongoError(f"Could not save post ID for {person_id}: {exc}") from exc
        if result is None:
            raise MongoError(f"No enrolled person has ID {person_id}.")
        return _person_from_document(result)

    def import_legacy(
        self,
        person_id: str,
        picture_ids: list[str],
        note_ids: list[str],
    ) -> None:
        """Insert legacy metadata once; retries never overwrite newer DB records."""
        now = datetime.now(timezone.utc)
        fields = {
            "person_id": person_id,
            "picture_ids": picture_ids,
            "note_ids": note_ids,
            "post_ids": [],
            "created_at": now,
            "updated_at": now,
        }
        _person_from_document(fields)
        try:
            self.collection.update_one(
                {"person_id": person_id},
                {"$setOnInsert": fields},
                upsert=True,
            )
        except Exception as exc:
            raise MongoError(f"Could not migrate {person_id} to MongoDB: {exc}") from exc

    def close(self) -> None:
        self.client.close()


def migrate_local_people(repository: PersonRepository, data_dir: Path) -> int:
    """Import id/image_paths/note_paths from legacy people.json and archive it.

    Existing MongoDB records win on retries. Names and facts from the legacy
    manifest are intentionally discarded — they now live in the graph DB.
    """
    root = data_dir.resolve()
    if root != repository.root.resolve():
        raise MongoError("Migration and repository must use the same data directory.")
    manifest = root / "people.json"
    if not manifest.exists():
        return 0
    try:
        original = manifest.read_bytes()
        payload = json.loads(original)
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        if "people" in payload:
            if not isinstance(payload["people"], list):
                raise ValueError("people must be a list")
            records = payload["people"]
        else:
            records = [dict(value, id=key) for key, value in payload.items()]

        # Validate all records before writing anything.
        prepared: list[tuple[str, list[str], list[str]]] = []
        seen: set[str] = set()
        for record in records:
            pid = record["id"]
            if not isinstance(pid, str) or not pid or pid in seen:
                raise ValueError("invalid or duplicate person ID")
            seen.add(pid)
            # Legacy records had image_paths, we convert to picture_ids 
            images = record.get("image_paths", [record.get("image")])
            picture_ids = [Path(p).stem for p in images if p] if images else []
            
            notes = record.get("note_paths", [])
            note_ids = [Path(p).stem for p in notes if p] if notes else []
            
            _person_from_document(
                {"person_id": pid, "picture_ids": picture_ids, "note_ids": note_ids, "post_ids": []}
            )
            existing = repository.collection.find_one({"person_id": pid})
            if existing is None:
                for value in images + notes:
                    if not repository.resolve_path(value).is_file():
                        raise MongoError(f"Legacy file is missing: {value}")
                for value in images:
                    if not repository.resolve_path(value).read_bytes().startswith(
                        PNG_SIGNATURE
                    ):
                        raise MongoError(f"Legacy face is not a PNG: {value}")
            prepared.append((pid, picture_ids, note_ids))

        for pid, picture_ids, note_ids in prepared:
            repository.import_legacy(pid, picture_ids, note_ids)
            # we no longer validate paths on the Person object here since they are just IDs.

        if manifest.read_bytes() != original:
            raise MongoError(
                "Legacy manifest changed during migration; originals retained for retry."
            )
        archive = root / "people.json.migrated"
        if archive.exists():
            raise MongoError(
                "Migration archive already exists; original manifest retained."
            )
        manifest.rename(archive)
        return len(prepared)
    except MongoError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MongoError(f"Could not migrate {manifest}: {exc}") from exc
