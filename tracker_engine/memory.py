"""Live in-memory state of currently tracked people.

MongoDB person records are authoritative. This module caches their names and
facts for display during a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackedPerson:
    person_id: str
    name: str | None = None   # session cache; authoritative source is MongoDB
    facts: list[str] = field(default_factory=list)
    # Set True whenever name or facts change — display.py reads and clears it
    display_dirty: bool = False


class Memory:
    """In-memory store of all enrolled people seen this session."""

    def __init__(self) -> None:
        self._people: dict[str, TrackedPerson] = {}

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, person_id: str) -> TrackedPerson | None:
        return self._people.get(person_id)

    def label(self, person_id: str) -> str:
        """Human-readable display label for a person."""
        person = self._people.get(person_id)
        if person is None:
            return f"Unknown ({person_id})"
        return person.name or f"Seen before ({person_id[-6:]})"

    def participants(self) -> dict[str, str | None]:
        """Map of person_id → name|None for all enrolled people."""
        return {pid: p.name for pid, p in self._people.items()}

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add(self, person_id: str) -> TrackedPerson:
        """Register a newly enrolled person (no name yet)."""
        person = TrackedPerson(person_id=person_id)
        self._people[person_id] = person
        return person

    def assign_name(self, person_id: str, name: str) -> None:
        """Cache a person's name for this session and flag the display for refresh."""
        person = self._people.get(person_id)
        if person is None:
            person = TrackedPerson(person_id=person_id)
            self._people[person_id] = person
        if person.name != name:
            person.name = name
            person.display_dirty = True

    def add_fact(self, person_id: str, fact: str) -> None:
        """Append a new fact for a person (skips duplicates)."""
        person = self._people.get(person_id)
        if person is None:
            return
        normalized = fact.strip().casefold()
        if not any(existing.casefold() == normalized for existing in person.facts):
            person.facts.append(fact.strip())
            person.display_dirty = True

    def mark_clean(self, person_id: str) -> None:
        """Called by display after it has redrawn with fresh data."""
        person = self._people.get(person_id)
        if person:
            person.display_dirty = False
