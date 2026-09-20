"""FastAPI handlers expose MongoDB path records and serve their images."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import tempfile
import unittest

from fastapi import HTTPException
from starlette.datastructures import UploadFile
from starlette.requests import Request

from backend.mongodb.handlers.people_handler import MongoError, Person
from tracker_engine.api import AddNote, RenamePerson, create_app


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACklEQVQIHWMAAgAABAABDTukuQAAAABJRU5ErkJggg=="
)


class FakeRepository:
    def __init__(self):
        self.people = {}
        self.images = {}

    def close(self):
        pass

    def list_people(self):
        return tuple(self.people.values())

    def get(self, person_id):
        try:
            return self.people[person_id]
        except KeyError as exc:
            raise MongoError(f"No enrolled person has ID {person_id}.") from exc

    def enroll(self, png):
        person = Person("person_111111111111", None, ["faces/person_111111111111.png"], [])
        self.images[person.id] = png
        self.people[person.id] = person
        return person

    def assign_name(self, person_id, name):
        current = self.get(person_id)
        person = replace(current, name=name, image_paths=[f"faces/{name}.png"])
        self.people[person.id] = person
        return person

    def image_bytes(self, person_id):
        self.get(person_id)
        return self.images[person_id]

    def add_note_path(self, person_id, value):
        person = replace(self.get(person_id), note_paths=[value])
        self.people[person_id] = person
        return person


class TrackerApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.app = create_app(self.repository)

    def endpoint(self, path, method):
        return next(route.endpoint for route in self.app.routes if route.path == path and method in route.methods)

    def request(self):
        return Request({"type": "http", "app": self.app, "method": "GET", "headers": []})

    def test_create_rename_and_read_png_from_mongo_repository(self):
        create = self.endpoint("/people", "POST")
        file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        self.addCleanup(file.close)
        file.write(PNG)
        file.seek(0)
        image = UploadFile(file=file, filename="face.png")
        person = asyncio.run(create(self.request(), image))
        self.assertEqual(person["note_paths"], [])
        self.assertEqual(person["image_paths"], ["faces/person_111111111111.png"])
        self.assertEqual(person["image_url"], "/people/person_111111111111/image")

        rename = self.endpoint("/people/{person_id}", "PATCH")
        self.assertEqual(rename(person["id"], RenamePerson(name="Ada"), self.request())["name"], "Ada")

        add_note = self.endpoint("/people/{person_id}/notes", "POST")
        updated = add_note(person["id"], AddNote(path="notes/ada.txt"), self.request())
        self.assertEqual(updated["image_paths"], ["faces/Ada.png"])
        self.assertEqual(updated["note_paths"], ["notes/ada.txt"])

        get_image = self.endpoint("/people/{person_id}/image", "GET")
        self.assertEqual(get_image(person["id"], self.request()).body, PNG)

    def test_missing_person_is_a_404(self):
        get_person = self.endpoint("/people/{person_id}", "GET")
        with self.assertRaises(HTTPException) as raised:
            get_person("person_000000000000", self.request())
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
