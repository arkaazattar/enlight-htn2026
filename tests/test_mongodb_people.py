"""MongoDB path records, file renames, and legacy migration tests."""

from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from mongodb.people import MongoError, PersonRepository, migrate_local_people, person_id_to_node_id


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACklEQVQIHWMAAgAABAABDTukuQAAAABJRU5ErkJggg=="
)


class FakeCollection:
    def __init__(self):
        self.documents = {}
        self.indexes = {"_id_": {"key": [("_id", 1)]}}

    def index_information(self):
        return self.indexes

    def create_index(self, keys, **options):
        self.indexes[options["name"]] = {"key": list(keys), **options}

    def insert_one(self, document):
        person_id = document["person_id"]
        if person_id in self.documents:
            raise RuntimeError("duplicate person")
        self.documents[person_id] = copy.deepcopy(document)

    def find(self, _query):
        return [copy.deepcopy(document) for document in self.documents.values()]

    def find_one(self, query):
        for document in self.documents.values():
            if all(
                document.get(key) != condition.get("$ne") if isinstance(condition, dict) and "$ne" in condition
                else document.get(key) == condition
                for key, condition in query.items()
            ):
                return copy.deepcopy(document)
        return None

    def find_one_and_update(self, query, update, *, return_document):
        person = self.find_one(query)
        if person is None:
            return None
        self._apply(person, update)
        self.documents[person["person_id"]] = copy.deepcopy(person)
        return person

    def update_one(self, query, update, *, upsert=False):
        person = self.find_one(query)
        if person is None:
            if not upsert:
                return
            person = {"person_id": query["person_id"]}
            person.update(copy.deepcopy(update.get("$setOnInsert", {})))
        self._apply(person, update)
        self.documents[person["person_id"]] = copy.deepcopy(person)

    @staticmethod
    def _apply(document, update):
        for key, value in update.get("$set", {}).items():
            document[key] = copy.deepcopy(value)
        for key, value in update.get("$addToSet", {}).items():
            document.setdefault(key, [])
            if value not in document[key]:
                document[key].append(value)
        for key in update.get("$unset", {}):
            document.pop(key, None)


class MongoPeopleTests(unittest.TestCase):
    def repository(self):
        repository = object.__new__(PersonRepository)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repository.root = Path(temporary.name)
        repository.collection = FakeCollection()
        repository.client = type("Client", (), {"close": lambda _self: None})()
        return repository

    def test_enrollment_name_and_facts_use_mongo_path_documents(self):
        repository = self.repository()
        person = repository.enroll(PNG)
        self.assertTrue(person.id.startswith("person_"))
        document = repository.collection.documents[person.id]
        self.assertEqual(document["image_paths"], [f"faces/{person.id}.png"])
        self.assertEqual(document["note_paths"], [])
        self.assertNotIn("face_png", document)
        self.assertFalse((repository.root / "people.json").exists())
        original = repository.image_path(person.id)

        renamed = repository.assign_name(person.id, "Ada")
        updated = repository.add_fact(person.id, "Studies physics")
        self.assertEqual(renamed.name, "Ada")
        self.assertEqual(renamed.image_paths, ["faces/Ada.png"])
        self.assertEqual(renamed.id, person.id)
        self.assertFalse(original.exists())
        self.assertEqual(updated.facts, ("Studies physics",))
        self.assertEqual(repository.image_bytes(person.id), PNG)

        second = repository.enroll(PNG)
        with self.assertRaisesRegex(MongoError, "already assigned"):
            repository.assign_name(second.id, "ada")

    def test_migration_preserves_images_and_context_and_archives_manifest(self):
        repository = self.repository()
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            repository.root = data_dir
            faces = data_dir / "faces"
            faces.mkdir()
            image = faces / "person_abcdef123456.png"
            image.write_bytes(PNG)
            (data_dir / "people.json").write_text(json.dumps({
                "version": 1,
                "people": [{"id": "person_abcdef123456", "name": None, "image": "faces/person_abcdef123456.png"}],
            }), encoding="utf-8")
            (data_dir / "person_context.json").write_text(json.dumps({
                "version": 2,
                "people": {
                    "person_abcdef123456": {
                        "facts": [{"text": "Studies physics", "evidence_ids": []}],
                    },
                },
            }), encoding="utf-8")

            self.assertEqual(migrate_local_people(repository, data_dir), 1)
            self.assertFalse((data_dir / "people.json").exists())
            self.assertTrue(image.exists())
            self.assertTrue((data_dir / "people.json.migrated").exists())
            self.assertTrue((data_dir / "person_context.json").exists())
            self.assertEqual(repository.get("person_abcdef123456").facts, ("Studies physics",))

    def test_notes_are_deduplicated_paths_and_missing_or_unsafe_paths_rejected(self):
        repository = self.repository()
        person = repository.enroll(PNG)
        notes = repository.root / "notes"
        notes.mkdir()
        (notes / "first.txt").write_text("Studies physics")
        repository.add_note_path(person.id, "notes/first.txt")
        updated = repository.add_note_path(person.id, "notes/first.txt")
        self.assertEqual(updated.note_paths, ["notes/first.txt"])
        for path in ("missing.txt", "../outside.txt", ""):
            with self.subTest(path=path), self.assertRaises(MongoError):
                repository.add_note_path(person.id, path)

    def test_correction_renames_every_face_and_keeps_notes(self):
        repository = self.repository()
        person = repository.enroll(PNG)
        second = repository.root / "faces" / "second.png"
        second.write_bytes(PNG)
        repository.collection.documents[person.id]["image_paths"].append("faces/second.png")
        repository.assign_name(person.id, "Ada")
        renamed = repository.assign_name(person.id, "Augusta")
        self.assertEqual(renamed.image_paths, ["faces/Augusta.png", "faces/Augusta_2.png"])
        self.assertFalse(second.exists())
        self.assertFalse((repository.root / "faces/Ada.png").exists())
        for path in renamed.image_paths:
            self.assertEqual((repository.root / path).read_bytes(), PNG)

    def test_failed_rename_keeps_original_record_and_image(self):
        repository = self.repository()
        person = repository.enroll(PNG)
        with patch.object(repository.collection, "find_one_and_update", side_effect=RuntimeError("offline")):
            with self.assertRaises(MongoError):
                repository.assign_name(person.id, "Ada")
        self.assertEqual(repository.get(person.id), person)
        self.assertEqual(repository.image_bytes(person.id), PNG)
        self.assertFalse((repository.root / "faces/Ada.png").exists())

    def test_existing_face_is_not_overwritten_on_rename(self):
        repository = self.repository()
        person = repository.enroll(PNG)
        target = repository.root / "faces/Ada.png"
        target.write_bytes(b"unrelated face")
        with self.assertRaises(MongoError):
            repository.assign_name(person.id, "Ada")
        self.assertEqual(target.read_bytes(), b"unrelated face")
        self.assertEqual(repository.get(person.id), person)

    def test_failed_migration_keeps_local_files_and_retry_preserves_db_updates(self):
        repository = self.repository()
        image = repository.root / "faces/abcdef123456.png"
        image.parent.mkdir()
        image.write_bytes(PNG)
        manifest = repository.root / "people.json"
        manifest.write_text(json.dumps({"abcdef123456": {"image": "faces/abcdef123456.png"}}))
        with patch.object(repository, "get", side_effect=MongoError("offline")):
            with self.assertRaises(MongoError):
                migrate_local_people(repository, repository.root)
        self.assertTrue(image.exists())
        self.assertTrue(manifest.exists())
        repository.assign_name("abcdef123456", "Ada")
        repository.add_fact("abcdef123456", "New fact")
        self.assertEqual(migrate_local_people(repository, repository.root), 1)
        self.assertEqual(repository.get("abcdef123456").name, "Ada")
        self.assertEqual(repository.get("abcdef123456").facts, ("New fact",))
        self.assertEqual(repository.image_bytes("abcdef123456"), PNG)
        self.assertEqual(migrate_local_people(repository, repository.root), 0)

    def test_migration_retains_concurrently_changed_manifest(self):
        repository = self.repository()
        image = repository.root / "faces/abcdef123456.png"
        image.parent.mkdir()
        image.write_bytes(PNG)
        manifest = repository.root / "people.json"
        manifest.write_text(json.dumps({"abcdef123456": {"image": "faces/abcdef123456.png"}}))
        original_get = repository.get
        def changed_get(pid):
            manifest.write_text(manifest.read_text() + " ")
            return original_get(pid)
        with patch.object(repository, "get", side_effect=changed_get):
            with self.assertRaisesRegex(MongoError, "changed during migration"):
                migrate_local_people(repository, repository.root)
        self.assertTrue(manifest.exists())
        self.assertTrue(image.exists())

    def test_store_adapter_uses_same_repository_after_restart(self):
        from tracker_engine.storage import PersonStore
        repository = self.repository()
        store = PersonStore(repository.root, repository)
        pid = store.enroll(PNG)
        store.assign_name(pid, "Ada")
        restarted = PersonStore(repository.root, repository)
        self.assertEqual(restarted.person_ids, [pid])
        self.assertEqual(restarted.get(pid).name, "Ada")
        self.assertEqual(restarted.image_path(pid).name, "Ada.png")
        self.assertFalse((repository.root / "people.json").exists())

    def test_person_id_conversion_accepts_legacy_prefix(self):
        self.assertEqual(person_id_to_node_id("person_abcdef123456"), int("abcdef123456", 16))
        self.assertEqual(person_id_to_node_id("abcdef123456"), int("abcdef123456", 16))


if __name__ == "__main__":
    unittest.main()
