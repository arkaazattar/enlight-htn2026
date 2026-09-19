"""Tracker-facing adapter for MongoDB person records and local media paths."""

from pathlib import Path

from mongodb.people import (
    MongoError as StoreError,
    PersonRepository,
    migrate_local_people,
    person_id_to_node_id,
)


class PersonStore:
    """Keep the tracker's stable-ID interface while persisting people in MongoDB."""

    def __init__(self, data_dir: Path, repository: PersonRepository | None = None) -> None:
        self.repository = repository or PersonRepository.from_environment(data_dir)
        try:
            migrate_local_people(self.repository, data_dir)
        except Exception:
            self.repository.close()
            raise

    @property
    def person_ids(self) -> list[str]:
        return [person.id for person in self.repository.list_people()]

    def enroll(self, png_bytes: bytes) -> str:
        return self.repository.enroll(png_bytes).id

    def get(self, person_id: str):
        return self.repository.get(person_id)

    def assign_name(self, person_id: str, name: str):
        return self.repository.assign_name(person_id, name)

    def add_fact(self, person_id: str, fact: str):
        return self.repository.add_fact(person_id, fact)

    def save_context(self, person_id: str, context: dict) -> None:
        self.repository.save_context(person_id, context)

    def image_path(self, person_id: str) -> Path:
        return self.repository.image_path(person_id)

    def load_gallery(self, recognizer):
        return self.repository.load_gallery(recognizer)

    def close(self) -> None:
        self.repository.close()
