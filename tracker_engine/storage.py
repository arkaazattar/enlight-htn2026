"""Face image and enrollment persistence.

Keeps enrolled face PNGs on disk and a simple JSON manifest.
people.json stores ONLY the image path — name lives in graph DB.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import cv2
import numpy as np


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class StoreError(Exception):
    """A face image or person record could not be used."""


def person_id_to_node_id(person_id: str) -> int:
    """Convert a 12-char hex person_id to an integer graph node ID."""
    return int(person_id, 16)


class PersonStore:
    """Minimal persistent store — face images + JSON manifest only.

    people.json schema per entry:
        { "image": "faces/<id>.png" }

    Name is authoritative in graph DB, not here.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir
        self.faces_dir = data_dir / "faces"
        self._manifest: dict[str, dict] = self._load()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def person_ids(self) -> list[str]:
        return list(self._manifest.keys())

    def image_path(self, person_id: str) -> Path:
        record = self._manifest.get(person_id)
        if record is None:
            raise StoreError(f"Unknown person: {person_id}")
        return self.root / record["image"]

    def enroll(self, png_bytes: bytes) -> str:
        """Save a new face PNG and return a fresh person_id."""
        if not png_bytes.startswith(PNG_SIGNATURE):
            raise StoreError("Enrollment image must be PNG.")
        self.faces_dir.mkdir(parents=True, exist_ok=True)
        person_id = uuid.uuid4().hex[:12]
        image_rel = f"faces/{person_id}.png"
        (self.root / image_rel).write_bytes(png_bytes)
        self._manifest[person_id] = {"image": image_rel}
        self._save()
        return person_id

    def load_gallery(self, recognizer: cv2.FaceRecognizerSF) -> dict[str, np.ndarray]:
        """Load face embeddings for all enrolled people."""
        gallery: dict[str, np.ndarray] = {}
        for person_id in list(self._manifest.keys()):
            path = self.image_path(person_id)
            if not path.is_file():
                continue
            img = cv2.imread(str(path))
            if img is None:
                continue
            gallery[person_id] = recognizer.feature(img).copy()
        return gallery

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        manifest_path = self.root / "people.json"
        if not manifest_path.exists():
            return {}
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise StoreError("people.json has unexpected format.")
            return data
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Cannot read people.json: {exc}") from exc

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "people.json").write_text(
            json.dumps(self._manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
