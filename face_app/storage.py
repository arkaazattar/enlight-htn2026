"""Persistent local person-to-face mapping."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ID_PATTERN = re.compile(r"person_[0-9a-f]{12}\Z")
INVALID_NAME_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"}
WINDOWS_RESERVED.update(f"COM{number}" for number in range(1, 10))
WINDOWS_RESERVED.update(f"LPT{number}" for number in range(1, 10))


class StoreError(Exception):
    """An identity record or face image cannot be used safely."""


@dataclass(frozen=True)
class Person:
    id: str
    name: str | None
    image: str

    @property
    def label(self) -> str:
        return self.name if self.name is not None else f"Seen before: {self.id}"


def validate_name(value: str) -> str:
    name = value.strip()
    if (
        not name
        or len(name) > 80
        or name.endswith(".")
        or any(character in INVALID_NAME_CHARS or ord(character) < 32 for character in name)
        or name.split(".")[0].upper() in WINDOWS_RESERVED
    ):
        raise StoreError(
            "Name must be 1-80 characters and cannot contain filename separators, "
            "reserved characters, or control characters."
        )
    return name


class PersonStore:
    def __init__(self, root: Path):
        self.root = root
        self.manifest = root / "people.json"
        self.faces = root / "faces"
        self._people = self._load()

    @property
    def people(self) -> tuple[Person, ...]:
        return tuple(self._people)

    def get(self, person_id: str) -> Person:
        for person in self._people:
            if person.id == person_id:
                return person
        raise StoreError(f"No enrolled person has ID {person_id}.")

    def image_path(self, person: Person) -> Path:
        return self.root / person.image

    def _load(self) -> list[Person]:
        if not self.manifest.exists():
            if self.faces.exists() and any(self.faces.glob("*.png")):
                raise StoreError(f"Saved face images exist, but the manifest is missing: {self.manifest}")
            return []
        try:
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Cannot read {self.manifest}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("people"), list):
            raise StoreError(f"Invalid manifest format: {self.manifest}")

        people: list[Person] = []
        ids: set[str] = set()
        names: set[str] = set()
        images: set[str] = set()
        for entry in payload["people"]:
            if not isinstance(entry, dict) or set(entry) != {"id", "name", "image"}:
                raise StoreError(f"Invalid person record in {self.manifest}")
            person_id, name, image = entry["id"], entry["name"], entry["image"]
            if not isinstance(person_id, str) or ID_PATTERN.fullmatch(person_id) is None:
                raise StoreError(f"Invalid person ID in {self.manifest}")
            if name is not None and (not isinstance(name, str) or validate_name(name) != name):
                raise StoreError(f"Invalid person name in {self.manifest}")
            expected_image = f"faces/{name or person_id}.png"
            if image != expected_image:
                raise StoreError(f"Image path for {person_id} must be {expected_image}")
            if person_id in ids or image in images or (name is not None and name.casefold() in names):
                raise StoreError(f"Duplicate person, name, or image in {self.manifest}")
            person = Person(person_id, name, image)
            if not self.image_path(person).is_file():
                raise StoreError(f"Saved face image is missing: {self.image_path(person)}")
            people.append(person)
            ids.add(person_id)
            images.add(image)
            if name is not None:
                names.add(name.casefold())
        return people

    def _save(self, people: list[Person]) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, prefix=".people-", suffix=".tmp", delete=False
            ) as output:
                temporary = Path(output.name)
                json.dump({"version": 1, "people": [asdict(person) for person in people]}, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.manifest)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def enroll(self, png_bytes: bytes) -> Person:
        if not png_bytes.startswith(PNG_SIGNATURE):
            raise StoreError("Enrollment image must be a PNG.")
        self.faces.mkdir(parents=True, exist_ok=True, mode=0o700)
        while True:
            person_id = f"person_{uuid.uuid4().hex[:12]}"
            if all(person.id != person_id for person in self._people):
                image = f"faces/{person_id}.png"
                target = self.root / image
                if not target.exists():
                    break
        created = False
        try:
            with target.open("xb") as output:
                created = True
                output.write(png_bytes)
                output.flush()
                os.fsync(output.fileno())
            person = Person(person_id, None, image)
            updated = [*self._people, person]
            self._save(updated)
        except OSError as exc:
            if created:
                target.unlink(missing_ok=True)
            raise StoreError(f"Could not save enrolled face: {exc}") from exc
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
        self._people = updated
        return person

    def assign_name(self, person_id: str, value: str) -> Person:
        name = validate_name(value)
        current = self.get(person_id)
        if current.name == name:
            return current
        for person in self._people:
            if person.id != person_id and person.name is not None and person.name.casefold() == name.casefold():
                raise StoreError(f"Name '{name}' is already assigned to {person.id}.")

        source = self.image_path(current)
        if not source.is_file():
            raise StoreError(f"Saved face image is missing: {source}")
        target = self.faces / f"{name}.png"
        updated_person = Person(person_id, name, f"faces/{name}.png")
        updated = [updated_person if person.id == person_id else person for person in self._people]
        if target == source:
            self._save(updated)
            self._people = updated
            return updated_person

        created = False
        try:
            with source.open("rb") as original, target.open("xb") as copy:
                created = True
                shutil.copyfileobj(original, copy)
                copy.flush()
                os.fsync(copy.fileno())
        except FileExistsError as exc:
            raise StoreError(f"Image filename already exists: {target.name}") from exc
        except OSError as exc:
            if created:
                target.unlink(missing_ok=True)
            raise StoreError(f"Could not rename face image: {exc}") from exc

        try:
            self._save(updated)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self._people = updated
        try:
            source.unlink()
        except OSError as exc:
            raise StoreError(
                f"Name was saved, but old image could not be removed: {source} ({exc})"
            ) from exc
        return updated_person
