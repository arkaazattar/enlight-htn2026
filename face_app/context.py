"""Temporary transcript spool and per-person Gemini identity evidence."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .storage import PersonStore, StoreError, validate_name


class ContextError(Exception):
    """Voice context could not be loaded or saved."""


@dataclass(frozen=True)
class VoiceEvent:
    id: str
    recorded_at: str
    text: str
    speakers: tuple[str, ...]
    words: tuple[dict, ...]
    person_id: str | None
    attribution: str
    start: float
    end: float

    @classmethod
    def create(cls, clip, transcript, person_id: str | None, reason: str):
        return cls(
            uuid.uuid4().hex, datetime.now(timezone.utc).isoformat(), transcript.text,
            transcript.speakers, transcript.words, person_id, reason, clip.start, clip.end,
        )


class VoiceEventStore:
    def __init__(self, root: Path):
        self.path = root / "voice_events.jsonl"
        self.events: list[VoiceEvent] = []
        if self.path.exists():
            number = 0
            try:
                with self.path.open(encoding="utf-8") as source:
                    for number, line in enumerate(source, 1):
                        if line.strip():
                            payload = json.loads(line)
                            payload["speakers"] = tuple(payload["speakers"])
                            payload["words"] = tuple(payload["words"])
                            self.events.append(VoiceEvent(**payload))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise ContextError(f"Invalid transcript spool {self.path} at line {number}: {exc}") from exc

    def append(self, event: VoiceEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            raise ContextError(f"Could not save transcript: {exc}") from exc
        self.events.append(event)

    def for_person(self, person_id: str) -> list[VoiceEvent]:
        return [event for event in self.events if event.person_id == person_id]


@dataclass(frozen=True)
class Fact:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IdentityAnalysis:
    name: str | None
    evidence_ids: tuple[str, ...]
    explicit_correction: bool
    facts: tuple[Fact, ...]


def parse_analysis(payload: dict) -> IdentityAnalysis:
    if not isinstance(payload, dict):
        raise ContextError("Gemini returned a non-object response.")
    name = payload.get("name")
    if name is not None:
        if not isinstance(name, str):
            raise ContextError("Gemini returned an invalid name.")
        try:
            name = validate_name(name)
        except StoreError as exc:
            raise ContextError(str(exc)) from exc
    evidence = payload.get("evidence_ids", [])
    correction = payload.get("explicit_correction", False)
    facts = payload.get("facts", [])
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ContextError("Gemini returned invalid name evidence.")
    if not isinstance(correction, bool) or not isinstance(facts, list):
        raise ContextError("Gemini returned invalid context fields.")
    parsed_facts = []
    for fact in facts:
        if (
            not isinstance(fact, dict) or not isinstance(fact.get("text"), str)
            or not isinstance(fact.get("evidence_ids"), list)
            or not all(isinstance(item, str) for item in fact["evidence_ids"])
        ):
            raise ContextError("Gemini returned an invalid fact.")
        parsed_facts.append(Fact(fact["text"].strip(), tuple(fact["evidence_ids"])))
    return IdentityAnalysis(name, tuple(evidence), correction, tuple(parsed_facts))


class GeminiAnalyzer:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ContextError("Gemini SDK is missing; install requirements.txt.") from exc
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20000))
        self.types = types
        self.model = model

    def analyze(
        self, person_id: str, events: list[VoiceEvent], prior_facts: list[Fact],
        unassigned: list[VoiceEvent] | None = None,
    ) -> IdentityAnalysis:
        source = [
            {"id": event.id, "text": event.text, "recorded_at": event.recorded_at}
            for event in events[-30:]
        ]
        prompt = (
            "Extract the name and simple personal facts of the one on-camera speaker with ID "
            f"{person_id}. Every provided transcript was linked to this face using lip motion. "
            "A name need not come from a self-introduction, but it must clearly identify this "
            "speaker, not someone they mention. Unassigned transcripts are context only; never "
            "cite them as identity or fact evidence. Return null name when uncertain. Cite exact "
            "transcript IDs that independently support the name. Set explicit_correction true "
            "only when the speaker clearly corrects their earlier name. Return only facts about "
            "this speaker, each with supporting IDs. Do not invent facts.\n"
            + json.dumps({
                "attributed_transcripts": source,
                "unassigned_context": [
                    {"id": item.id, "text": item.text, "recorded_at": item.recorded_at}
                    for item in (unassigned or [])[-10:]
                ],
                "prior_facts": [asdict(fact) for fact in prior_facts],
            })
        )
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "explicit_correction": {"type": "boolean"},
                "facts": {"type": "array", "items": {"type": "object", "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                }, "required": ["text", "evidence_ids"]}},
            },
            "required": ["name", "evidence_ids", "explicit_correction", "facts"],
        }
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config=self.types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema,
                ),
            )
            return parse_analysis(json.loads(response.text))
        except Exception as exc:
            if isinstance(exc, ContextError):
                raise
            raise ContextError(f"Gemini analysis failed: {exc}") from exc


class PersonContextStore:
    def __init__(self, root: Path):
        self.path = root / "person_context.json"
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"version": 1, "people": {}}
        except (OSError, ValueError) as exc:
            raise ContextError(f"Could not read {self.path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("people"), dict):
            raise ContextError(f"Invalid context format: {self.path}")
        self.people = payload["people"]

    def facts(self, person_id: str) -> list[Fact]:
        return [Fact(item["text"], tuple(item["evidence_ids"])) for item in self.people.get(person_id, {}).get("facts", [])]

    def needs_processing(self, person_id: str, events: list[VoiceEvent]) -> bool:
        processed = set(self.people.get(person_id, {}).get("processed_event_ids", []))
        return any(event.id not in processed for event in events)

    def apply(self, person_id: str, events: list[VoiceEvent], analysis: IdentityAnalysis, store: PersonStore) -> str:
        allowed = {event.id for event in events if event.person_id == person_id}
        record = self.people.setdefault(person_id, {"facts": [], "processed_event_ids": []})
        existing_facts = {item["text"].casefold() for item in record["facts"]}
        for fact in analysis.facts:
            if fact.text and set(fact.evidence_ids) & allowed and fact.text.casefold() not in existing_facts:
                record["facts"].append(asdict(fact))
                existing_facts.add(fact.text.casefold())
        outcome = "Gemini gathered context; name remains unconfirmed."
        current = store.get(person_id)
        evidence = set(analysis.evidence_ids) & allowed
        if analysis.name and len(evidence) >= 2:
            if current.name is None or current.name == analysis.name or analysis.explicit_correction:
                try:
                    named = store.assign_name(person_id, analysis.name)
                    outcome = f"Named {named.id}: {named.name}"
                except (StoreError, OSError) as exc:
                    outcome = f"Name not assigned: {exc}"
            else:
                outcome = "Different name found; an explicit correction is required."
        record["processed_event_ids"] = sorted(set(record["processed_event_ids"]) | allowed)
        self._save()
        return outcome

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, prefix=".context-", delete=False) as output:
                temporary = Path(output.name)
                json.dump({"version": 1, "people": self.people}, output, indent=2, ensure_ascii=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
