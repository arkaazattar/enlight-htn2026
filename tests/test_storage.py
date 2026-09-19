"""Tests for the persistent person/image contract."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from face_app.storage import PersonStore, StoreError


# A valid 1x1 PNG is enough to test storage without OpenCV or a webcam.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACklEQVQIHWMAAgAABAABDTukuQAAAABJRU5ErkJggg=="
)


class PersonStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.store = PersonStore(self.root)

    def test_enrollment_persists_and_name_correction_updates_image(self) -> None:
        person = self.store.enroll(PNG)
        first_image = self.store.image_path(person)
        self.assertTrue(first_image.is_file())
        self.assertEqual(PersonStore(self.root).get(person.id).label, f"Seen before: {person.id}")

        named = self.store.assign_name(person.id, "Jon")
        self.assertEqual(named.id, person.id)
        self.assertEqual(named.label, "Jon")
        self.assertEqual(named.image, "faces/Jon.png")
        self.assertFalse(first_image.exists())
        self.assertTrue(self.store.image_path(named).exists())

        corrected = self.store.assign_name(person.id, "Jonathan")
        self.assertFalse(self.store.image_path(named).exists())
        self.assertEqual(PersonStore(self.root).get(person.id), corrected)
        self.assertEqual(corrected.image, "faces/Jonathan.png")
        manifest = json.loads((self.root / "people.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["people"], [
            {"id": person.id, "name": "Jonathan", "image": "faces/Jonathan.png"}
        ])

    def test_conflicting_name_and_existing_file_are_not_overwritten(self) -> None:
        first = self.store.enroll(PNG)
        second = self.store.enroll(PNG)
        self.store.assign_name(first.id, "Jon")
        second_image = self.store.image_path(second)

        with self.assertRaisesRegex(StoreError, "already assigned"):
            self.store.assign_name(second.id, "jon")
        self.assertTrue(second_image.exists())
        self.assertIsNone(PersonStore(self.root).get(second.id).name)

        unrelated = self.root / "faces" / "Alex.png"
        unrelated.write_bytes(b"do not overwrite")
        with self.assertRaisesRegex(StoreError, "already exists"):
            self.store.assign_name(second.id, "Alex")
        self.assertEqual(unrelated.read_bytes(), b"do not overwrite")
        self.assertTrue(second_image.exists())

    def test_bad_name_and_missing_image_do_not_change_record(self) -> None:
        person = self.store.enroll(PNG)
        for name in ("", "../Jon", "CON", "Jon/Smith", "Jon."):
            with self.subTest(name=name), self.assertRaises(StoreError):
                self.store.assign_name(person.id, name)
        self.assertIsNone(PersonStore(self.root).get(person.id).name)

        self.store.image_path(person).unlink()
        with self.assertRaisesRegex(StoreError, "missing"):
            PersonStore(self.root)

    def test_manifest_write_failure_keeps_original_image(self) -> None:
        person = self.store.enroll(PNG)
        original = self.store.image_path(person)
        with patch.object(self.store, "_save", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.store.assign_name(person.id, "Jon")
        self.assertTrue(original.exists())
        self.assertFalse((self.root / "faces" / "Jon.png").exists())
        self.assertIsNone(PersonStore(self.root).get(person.id).name)


if __name__ == "__main__":
    unittest.main()
