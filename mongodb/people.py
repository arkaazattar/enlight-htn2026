"""MongoDB person records with paths to local images and note files."""

from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
INVALID_NAME_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"}
WINDOWS_RESERVED.update(f"COM{number}" for number in range(1, 10))
WINDOWS_RESERVED.update(f"LPT{number}" for number in range(1, 10))


class MongoError(Exception):
    """MongoDB person storage is unavailable or contains invalid data."""


@dataclass(frozen=True)
class Person:
    """A stable identity with file paths relative to the configured data directory."""

    id: str
    name: str | None
    image_paths: list[str]
    note_paths: list[str]
    facts: tuple[str, ...] = ()
    context: dict | None = None

    @property
    def label(self) -> str:
        return self.name or f"Seen before: {self.id}"


def validate_name(value: str) -> str:
    if not isinstance(value, str):
        raise MongoError("Name must be a string.")
    name = value.strip()
    if (
        not name
        or len(name) > 80
        or name.endswith(".")
        or any(character in INVALID_NAME_CHARS or ord(character) < 32 for character in name)
        or name.split(".")[0].upper() in WINDOWS_RESERVED
    ):
        raise MongoError(
            "Name must be 1-80 characters and cannot contain filename separators, "
            "reserved characters, or control characters."
        )
    return name


def person_id_to_node_id(person_id: str) -> int:
    """Convert both legacy and current stable person IDs to graph node IDs."""
    value = person_id.removeprefix("person_")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise MongoError(f"Invalid person ID: {person_id}") from exc


def _facts_from(document: dict) -> tuple[str, ...]:
    direct = document.get("facts")
    if isinstance(direct, list) and all(isinstance(item, str) for item in direct):
        return tuple(item for item in direct if item.strip())
    context = document.get("context", {})
    legacy_facts = context.get("facts", []) if isinstance(context, dict) else []
    return tuple(
        item["text"] for item in legacy_facts
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
    )


def _person_from_document(document: dict) -> Person:
    person_id = document.get("person_id")
    name = document.get("name")
    if not isinstance(person_id, str) or not person_id:
        raise MongoError("MongoDB person document has no valid person_id.")
    if name is not None and not isinstance(name, str):
        raise MongoError(f"MongoDB person {person_id} has an invalid name.")
    paths = {}
    for field in ("image_paths", "note_paths"):
        value = document.get(field)
        if not isinstance(value, list) or any(not isinstance(p, str) or not p.strip() for p in value):
            raise MongoError(f"MongoDB person {person_id} has invalid {field}; expected a list of strings.")
        paths[field] = list(value)
    if not paths["image_paths"]:
        raise MongoError(f"MongoDB person {person_id} has no face image paths.")
    context = document.get("context", {})
    if not isinstance(context, dict):
        raise MongoError(f"MongoDB person {person_id} has an invalid context.")
    return Person(person_id, name, paths["image_paths"], paths["note_paths"],
                  _facts_from(document), copy.deepcopy(context))


class PersonRepository:
    """One MongoDB document per person; image and note contents remain on disk."""

    def __init__(self, uri: str, database: str, collection: str, data_dir: Path | None = None):
        self.root = (data_dir or Path(__file__).resolve().parent.parent / "data").resolve()
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise MongoError("MongoDB support is missing; install requirements.txt.") from exc
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.client.admin.command("ping")
            self.collection = self.client[database][collection]
            self._ensure_index([("person_id", 1)], unique=True, name="person_id_unique")
            self._ensure_index(
                [("name_key", 1)], unique=True, name="name_key_unique",
                partialFilterExpression={"name_key": {"$type": "string"}},
            )
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
        expected_options = {key: value for key, value in options.items() if key != "name"}
        for specification in self.collection.index_information().values():
            key_specification = specification.get("key", ())
            current_keys = list(key_specification.items()) if hasattr(key_specification, "items") else list(key_specification)
            if current_keys == expected_keys and all(specification.get(key) == value for key, value in expected_options.items()):
                return
        self.collection.create_index(keys, **options)

    def list_people(self) -> tuple[Person, ...]:
        try:
            documents = self.collection.find({})
            return tuple(sorted((_person_from_document(document) for document in documents), key=lambda person: person.id))
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

    def resolve_path(self, value: str) -> Path:
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise MongoError(f"File path must be inside the data directory: {value}")
        return path

    def image_path(self, person_id: str) -> Path:
        return self.resolve_path(self.get(person_id).image_paths[0])

    def enroll(self, png_bytes: bytes) -> Person:
        if not png_bytes.startswith(PNG_SIGNATURE):
            raise MongoError("Enrollment image must be a PNG.")
        person_id = f"person_{uuid.uuid4().hex[:12]}"
        relative = f"faces/{person_id}.png"
        path = self.resolve_path(relative)
        now = datetime.now(timezone.utc)
        document = {
            "schema_version": 3,
            "person_id": person_id,
            "name": None,
            "image_paths": [relative],
            "note_paths": [],
            "facts": [],
            "context": {},
            "created_at": now,
            "updated_at": now,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(png_bytes)
            self.collection.insert_one(document)
        except Exception as exc:
            # A network timeout can occur after MongoDB commits. Keep the image
            # so a committed document can never point at a deleted face.
            raise MongoError(f"Could not create {person_id}: {exc}") from exc
        return _person_from_document(document)

    def assign_name(self, person_id: str, value: str) -> Person:
        name = validate_name(value)
        current = self.get(person_id)
        name_key = name.casefold()
        try:
            existing = self.collection.find_one({"name_key": name_key, "person_id": {"$ne": person_id}})
        except Exception as exc:
            raise MongoError(f"Could not check name availability: {exc}") from exc
        if existing is not None:
            raise MongoError(f"Name '{name}' is already assigned to {existing['person_id']}.")
        destinations = [
            f"faces/{name}.png" if index == 0 else f"faces/{name}_{index + 1}.png"
            for index in range(len(current.image_paths))
        ]
        if current.name == name and current.image_paths == destinations:
            return current
        copies = []
        try:
            for source_value, target_value in zip(current.image_paths, destinations):
                source, target = self.resolve_path(source_value), self.resolve_path(target_value)
                if not source.is_file():
                    raise MongoError(f"Saved face is missing: {source_value}")
                if source == target:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation prevents overwriting unrelated saved faces.
                with target.open("xb") as output:
                    copies.append(target)
                    output.write(source.read_bytes())
        except Exception as exc:
            for path in copies:
                path.unlink(missing_ok=True)
            raise MongoError(f"Could not prepare face rename for {person_id}: {exc}") from exc
        try:
            from pymongo import ReturnDocument

            result = self.collection.find_one_and_update(
                {"person_id": person_id, "name": current.name, "image_paths": current.image_paths},
                {"$set": {"name": name, "name_key": name_key, "image_paths": destinations,
                          "updated_at": datetime.now(timezone.utc)}},
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            # Read back after an ambiguous write before deciding which files are
            # safe to remove. If MongoDB is unavailable, retain both versions.
            try:
                saved = self.get(person_id)
            except Exception:
                raise MongoError(f"Could not verify rename for {person_id}; face copies retained.") from exc
            if saved.name == name and saved.image_paths == destinations:
                result = self.collection.find_one({"person_id": person_id})
            else:
                for path in copies:
                    if path.relative_to(self.root).as_posix() not in saved.image_paths:
                        path.unlink(missing_ok=True)
                raise MongoError(f"Could not rename {person_id} in MongoDB: {exc}") from exc
        if result is None:
            # Another writer changed the record; retain copies for recovery.
            raise MongoError(f"Person {person_id} changed during rename; retry the operation.")
        for old in current.image_paths:
            if old not in destinations:
                try:
                    self.resolve_path(old).unlink(missing_ok=True)
                except OSError:
                    pass  # A redundant old copy is safe; the new paths are valid.
        return _person_from_document(result)

    def add_note_path(self, person_id: str, value: str) -> Person:
        """Link an existing note file without storing its contents in the record."""
        if not isinstance(value, str) or not value.strip():
            raise MongoError("Note path must be a nonempty string.")
        path = self.resolve_path(value)
        if not path.is_file():
            raise MongoError(f"Note file is missing: {value}")
        from pymongo import ReturnDocument
        try:
            result = self.collection.find_one_and_update(
                {"person_id": person_id},
                {"$addToSet": {"note_paths": path.relative_to(self.root).as_posix()},
                 "$set": {"updated_at": datetime.now(timezone.utc)}},
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            raise MongoError(f"Could not save note path for {person_id}: {exc}") from exc
        if result is None:
            raise MongoError(f"No enrolled person has ID {person_id}.")
        return _person_from_document(result)

    def save_context(self, person_id: str, context: dict) -> None:
        self.get(person_id)
        try:
            self.collection.update_one(
                {"person_id": person_id},
                {"$set": {"context": copy.deepcopy(context), "updated_at": datetime.now(timezone.utc)}},
            )
        except Exception as exc:
            raise MongoError(f"Could not save context for {person_id}: {exc}") from exc

    def add_fact(self, person_id: str, fact: str) -> Person:
        text = fact.strip()
        if not text:
            raise MongoError("Fact cannot be empty.")
        try:
            from pymongo import ReturnDocument

            result = self.collection.find_one_and_update(
                {"person_id": person_id},
                {"$addToSet": {"facts": text}, "$set": {"updated_at": datetime.now(timezone.utc)}},
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            raise MongoError(f"Could not save a fact for {person_id}: {exc}") from exc
        if result is None:
            raise MongoError(f"No enrolled person has ID {person_id}.")
        return _person_from_document(result)

    def image_bytes(self, person_id: str) -> bytes:
        try:
            return self.image_path(person_id).read_bytes()
        except OSError as exc:
            raise MongoError(f"Could not read face for {person_id}: {exc}") from exc

    def load_gallery(self, recognizer) -> dict[str, np.ndarray]:
        gallery: dict[str, np.ndarray] = {}
        for person in self.list_people():
            image = cv2.imdecode(np.frombuffer(self.image_bytes(person.id), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise MongoError(f"Could not decode the saved face for {person.id}.")
            gallery[person.id] = recognizer.feature(image).copy()
        return gallery

    def import_legacy(self, person_id: str, name: str | None, image_paths: list[str],
                      note_paths: list[str], context: dict) -> None:
        """Insert legacy metadata once; retries never overwrite newer DB records."""
        now = datetime.now(timezone.utc)
        fields = {
            "schema_version": 3,
            "person_id": person_id,
            "name": name,
            "image_paths": image_paths,
            "note_paths": note_paths,
            "facts": list(_facts_from({"context": context})),
            "context": copy.deepcopy(context),
            "created_at": now,
            "updated_at": now,
        }
        _person_from_document(fields)
        if name is not None:
            fields["name_key"] = validate_name(name).casefold()
        try:
            self.collection.update_one({"person_id": person_id}, {"$setOnInsert": fields}, upsert=True)
        except Exception as exc:
            raise MongoError(f"Could not migrate {person_id} to MongoDB: {exc}") from exc

    def close(self) -> None:
        self.client.close()


def migrate_local_people(repository: PersonRepository, data_dir: Path) -> int:
    """Import metadata, preserve images/notes, and archive the verified manifest.

    Existing MongoDB records win on retries. Legacy speech logs are untouched.
    The context file remains available as evidence and is never deleted here.
    """
    root = data_dir.resolve()
    if root != repository.root:
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
        context_path = root / "person_context.json"
        context_bytes = context_path.read_bytes() if context_path.exists() else None
        contexts = json.loads(context_bytes).get("people", {}) if context_bytes else {}
        if not isinstance(contexts, dict):
            raise ValueError("context people must be an object")
        # Validate the complete input before making any writes.
        prepared = []
        seen = set()
        for record in records:
            pid, name = record["id"], record.get("name")
            if not isinstance(pid, str) or not pid or pid in seen:
                raise ValueError("invalid or duplicate person ID")
            seen.add(pid)
            if name is not None:
                name = validate_name(name)
            images = record.get("image_paths", [record.get("image")])
            notes = record.get("note_paths", [])
            context = contexts.get(pid, {})
            _person_from_document(dict(person_id=pid, name=name, image_paths=images,
                                       note_paths=notes, context=context))
            existing = repository.collection.find_one({"person_id": pid})
            # A prior successful import/rename may have moved the old image.
            if existing is None:
                for value in images + notes:
                    if not repository.resolve_path(value).is_file():
                        raise MongoError(f"Legacy file is missing: {value}")
                for value in images:
                    if not repository.resolve_path(value).read_bytes().startswith(PNG_SIGNATURE):
                        raise MongoError(f"Legacy face is not a PNG: {value}")
            prepared.append((pid, name, images, notes, context))
        for pid, name, images, notes, context in prepared:
            repository.import_legacy(pid, name, images, notes, context)
            person = repository.get(pid)
            if person.name:
                person = repository.assign_name(pid, person.name)
            for value in person.image_paths + person.note_paths:
                if not repository.resolve_path(value).is_file():
                    raise MongoError(f"Migrated file is missing: {value}")
        if manifest.read_bytes() != original or (
            context_path.read_bytes() if context_path.exists() else None
        ) != context_bytes:
            raise MongoError("Legacy files changed during migration; originals retained for retry.")
        # Keep a backup, but never use the local manifest for new writes.
        archive = root / "people.json.migrated"
        if archive.exists():
            raise MongoError("Migration archive already exists; original manifest retained.")
        manifest.rename(archive)
        return len(prepared)
    except MongoError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MongoError(f"Could not migrate {manifest}: {exc}") from exc
