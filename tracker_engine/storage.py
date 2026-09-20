"""Tracker-facing adapter for MongoDB person records and local media paths."""

from pathlib import Path

from backend.mongodb.handlers.people_handler import (
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

    def image_path(self, person_id: str):
        return self.repository.image_path(person_id)

    def load_gallery(self, recognizer):
        return self.repository.load_gallery(recognizer)

    def close(self) -> None:
        self.repository.close()
