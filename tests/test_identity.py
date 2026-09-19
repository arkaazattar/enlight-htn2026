"""Evidence validation, direct handoff retries, and legacy migration."""

from __future__ import annotations

import base64
import json
import queue
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from face_app.context import (
    AnalysisRequest, ContextError, Fact, GeminiAnalyzer, IdentityProposal,
    LegacyReplay, PersonContextStore, ProviderError, PROPOSAL_SCHEMA, parse_analysis,
)
from face_app.identity import IdentityCoordinator
from face_app.speech import SpeechTurn
from face_app.storage import PersonStore

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAACklEQVQIHWMAAgAABAABDTukuQAAAABJRU5ErkJggg==")


class FakeWorker:
    def __init__(self):
        self.requests = []
        self.completed = queue.Queue()
        self.closed = False

    def submit(self, request):
        self.requests.append(request)

    def respond(self, value):
        self.completed.put((self.requests[-1], value))

    def close(self):
        self.closed = True


class IdentityFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.people = PersonStore(self.root)
        self.person = self.people.enroll(PNG)
        self.other = self.people.enroll(PNG)
        self.context = PersonContextStore(self.root)

    def turn(self, key, *, clip=None, person=None, text="My name is Jon."):
        return SpeechTurn(key, clip or f"clip-{key}", "2026-09-19T00:00:00Z", text, "speaker_0", 0, 1,
                          person_id=person or self.person.id, attribution="one clearly active speaking face")

    def request(self, *turns):
        return AnalysisRequest(tuple(turns), tuple(turns), {p.id: p.name for p in self.people.people}, self.context.snapshot())

    def proposal(self, *ids, name="Jon", corrections=(), facts=(), person=None):
        return IdentityProposal(person or self.person.id, name, ids, corrections, facts)

class IdentityTests(IdentityFixture):
    def test_two_distinct_clips_are_required_and_candidate_survives_restart(self):
        first, same_clip = self.turn("one"), self.turn("two", clip="clip-one")
        self.context.apply(self.request(first, same_clip), [self.proposal("one", "two")], self.people)
        self.assertIsNone(self.people.get(self.person.id).name)
        self.context = PersonContextStore(self.root)
        second = self.turn("three")
        self.context.apply(self.request(second), [self.proposal("three")], self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        self.assertTrue((self.root / "faces" / "Jon.png").is_file())
        self.assertFalse((self.root / "faces" / f"{self.person.id}.png").exists())
        self.context.apply(self.request(second), [self.proposal("three")], self.people)
        self.assertEqual(len(self.context.people[self.person.id]["evidence"]), 3)

    def test_each_person_can_gain_separate_facts_from_same_conversation(self):
        first = self.turn("one", text="I study physics.")
        second = self.turn("two", person=self.other.id, text="I play piano.")
        self.context.apply(self.request(first, second), [
            self.proposal(name=None, facts=(Fact("Studies physics", ("one",)),)),
            self.proposal(name=None, facts=(Fact("Plays piano", ("two",)),), person=self.other.id),
        ], self.people)
        saved = PersonContextStore(self.root)
        self.assertEqual(saved.people[self.person.id]["facts"][0]["text"], "Studies physics")
        self.assertEqual(saved.people[self.other.id]["evidence"]["two"]["text"], "I play piano.")
        self.assertNotIn("two", saved.people[self.person.id]["evidence"])

    def test_all_citations_must_exist_and_belong_to_target_person(self):
        one, other = self.turn("one"), self.turn("other", person=self.other.id)
        unassigned = replace(self.turn("unknown"), person_id=None)
        for bad in ("other", "unknown", "invented"):
            with self.subTest(bad=bad), self.assertRaises(ContextError):
                self.context.apply(
                    self.request(one, other, unassigned),
                    [self.proposal(name=None, facts=(Fact("Some fact", ("one", bad)),))],
                    self.people,
                )
        self.assertEqual(self.context.people, {})
        self.assertFalse(self.context.path.exists())

    def test_corrections_need_two_clips_and_explicit_evidence(self):
        self.people.assign_name(self.person.id, "Jon")
        one, two = self.turn("one"), self.turn("two")
        self.context.apply(self.request(one, two), [self.proposal("one", "two", name="Jonathan")], self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        correction = self.turn("correction", text="Actually my name is Jonathan, not Jon.")
        self.context.apply(self.request(correction), [self.proposal("correction", name="Jonathan", corrections=("correction",))], self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jonathan")
        self.assertTrue((self.root / "faces" / "Jonathan.png").is_file())

    def test_name_conflicts_keep_faces_and_candidate_evidence(self):
        self.people.assign_name(self.other.id, "Jon")
        one, two = self.turn("one"), self.turn("two")
        messages = self.context.apply(self.request(one, two), [self.proposal("one", "two")], self.people)
        self.assertIn("Name conflict", messages[-1])
        self.assertIsNone(self.people.get(self.person.id).name)
        self.assertTrue(self.people.image_path(self.people.get(self.other.id)).exists())
        self.assertIn("jon", self.context.people[self.person.id]["candidates"])

    def test_old_correction_evidence_cannot_reverse_a_later_name(self):
        self.people.assign_name(self.person.id, "Wrong Name")
        one, two = self.turn("one"), self.turn("two")
        self.context.apply(self.request(one, two), [self.proposal("one", "two", corrections=("one",))], self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        self.context.apply(self.request(self.turn("three")), [self.proposal("one", "two", name="Wrong Name", corrections=("one",))], self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")

    def test_failed_context_save_can_be_replayed_after_name_was_applied(self):
        one, two = self.turn("one"), self.turn("two")
        request = self.request(one, two)
        proposal = self.proposal("one", "two", facts=(Fact("Name is Jon", ("one", "two")),))
        with patch.object(self.context, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.context.apply(request, [proposal], self.people)
        self.assertEqual(self.context.people, {})
        self.context.apply(request, [proposal], self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        self.assertEqual(len(self.context.people[self.person.id]["facts"]), 1)

    def test_gemini_receives_names_dialogue_and_prior_evidence(self):
        one = self.turn("one")
        self.context.apply(self.request(one), [self.proposal("one")], self.people)
        self.people.assign_name(self.other.id, "Sam")
        reply = self.turn("two", text="Yes, Jon is me.")
        context_turn = self.turn("address", person=self.other.id, text="Jon, is that your project?")
        request = self.request(context_turn, reply)
        analyzer = GeminiAnalyzer("test-key")
        self.addCleanup(analyzer.close)
        response = {"proposals": [{
            "person_id": self.person.id, "name": "Jon", "evidence_ids": ["one", "two"],
            "correction_ids": [], "facts": [],
        }]}
        with patch.object(analyzer.client.models, "generate_content", return_value=SimpleNamespace(text=json.dumps(response))) as generate:
            proposals = analyzer.analyze(request)
        payload = json.loads(generate.call_args.kwargs["contents"])
        self.assertEqual(payload["participants"][self.other.id], "Sam")
        self.assertIn("one", payload["prior_context"][self.person.id]["evidence"])
        self.assertIn("no particular introduction", generate.call_args.kwargs["config"].system_instruction)
        self.context.apply(request, proposals, self.people)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        from google.genai import types
        types.Schema.model_validate(PROPOSAL_SCHEMA)  # Exercise the real enterprise schema validator.

    def test_provider_errors_classify_transient_vs_authentication(self):
        analyzer = GeminiAnalyzer("test-key")
        self.addCleanup(analyzer.close)
        class APIError(Exception):
            def __init__(self, code):
                self.code = code
        for code, retryable in ((429, True), (503, True), (403, False), (400, False)):
            with patch.object(analyzer.client.models, "generate_content", side_effect=APIError(code)):
                with self.assertRaises(ProviderError) as raised:
                    analyzer.analyze(self.request(self.turn("one")))
                self.assertEqual(raised.exception.retryable, retryable)

    def test_enterprise_client_uses_adc_and_missing_adc_is_actionable(self):
        from google.auth.exceptions import DefaultCredentialsError
        credentials = object()
        with patch("google.auth.default", return_value=(credentials, "project")), patch("google.genai.Client") as client:
            GeminiAnalyzer(enterprise=True, project="example-project", location="global")
        self.assertIs(client.call_args.kwargs["credentials"], credentials)
        self.assertTrue(client.call_args.kwargs["enterprise"])
        with patch("google.auth.default", side_effect=DefaultCredentialsError("missing")):
            with self.assertRaisesRegex(ContextError, "gcloud auth application-default login"):
                GeminiAnalyzer(enterprise=True, project="example-project", location="global")

    def test_invalid_response_shape_is_rejected(self):
        for payload in ([], {}, {"proposals": [{"person_id": self.person.id, "name": 7}]}):
            with self.assertRaises(ContextError):
                parse_analysis(payload)


class CoordinatorTests(IdentityFixture):
    def coordinator(self, *, legacy=None, capacity=128):
        worker = FakeWorker()
        coordinator = IdentityCoordinator(None, self.context, self.people, legacy, worker=worker, capacity=capacity)
        self.addCleanup(coordinator.close)
        return coordinator, worker

    def test_retry_backoff_deduplication_and_new_speech_during_request(self):
        coordinator, worker = self.coordinator()
        one, two = self.turn("one"), self.turn("two")
        coordinator.submit([one])
        coordinator.poll(0)
        worker.respond(ProviderError("rate limited", True))
        coordinator.poll(1)
        self.assertEqual(coordinator.retry_at, 3)
        coordinator.submit([one, two])
        self.assertEqual(len(coordinator.pending), 2)
        coordinator.poll(2)
        self.assertEqual(len(worker.requests), 1)
        coordinator.poll(3)
        worker.respond((self.proposal("one"),))
        coordinator.poll(4)
        self.assertIsNone(self.people.get(self.person.id).name)
        self.assertEqual([t.turn_id for t in worker.requests[-1].turns], ["two"])
        worker.respond((self.proposal("two"),))
        coordinator.poll(5)
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        self.assertFalse(coordinator.pending)
        self.assertFalse((self.root / "voice_events.jsonl").exists())

    def test_backoff_caps_and_auth_failure_pauses_without_losing_pending(self):
        coordinator, worker = self.coordinator()
        coordinator.submit([self.turn("one")])
        now = 0
        coordinator.poll(now)
        for delay in (2, 4, 8, 16, 32, 60, 60):
            worker.respond(ProviderError("offline", True))
            coordinator.poll(now)
            self.assertEqual(coordinator.retry_at, now + delay)
            now += delay
            coordinator.poll(now)
        worker.respond(ProviderError("permission denied", False))
        coordinator.poll(now + 1)
        self.assertTrue(coordinator.paused)
        count = len(worker.requests)
        coordinator.poll(now + 1000)
        self.assertEqual(len(worker.requests), count)
        self.assertEqual(coordinator.close(), 1)

    def test_queue_bounds_and_unassigned_context_do_not_trigger_naming(self):
        coordinator, worker = self.coordinator(capacity=1)
        unknown = replace(self.turn("unknown"), person_id=None)
        coordinator.submit([unknown])
        coordinator.poll(0)
        self.assertFalse(worker.requests)
        coordinator.submit([self.turn("one"), self.turn("two")])
        self.assertEqual(len(coordinator.pending), 1)
        self.assertTrue(any("queue is full" in message for message in coordinator.notices))
        coordinator.poll(1)
        self.assertIn("unknown", [turn.turn_id for turn in worker.requests[-1].conversation])
        self.assertEqual(coordinator.close(), 1)

    def test_missing_gemini_keeps_bounded_pending_speech_in_memory(self):
        coordinator = IdentityCoordinator(None, self.context, self.people, capacity=1)
        coordinator.submit([self.turn("one"), self.turn("two")])
        coordinator.poll(0)
        self.assertTrue(coordinator.paused)
        self.assertEqual(len(coordinator.pending), 1)
        self.assertEqual(coordinator.close(), 1)
        self.assertFalse(self.context.path.exists())
        self.assertFalse((self.root / "voice_events.jsonl").exists())

    def write_legacy(self, turns):
        path = self.root / "voice_events.jsonl"
        path.write_text("".join(json.dumps({
            "id": turn.turn_id, "recorded_at": turn.recorded_at, "text": turn.text,
            "speakers": [turn.speaker_id] if turn.speaker_id else [], "words": [],
            "person_id": turn.person_id, "attribution": turn.attribution, "start": turn.start, "end": turn.end,
        }) + "\n" for turn in turns))
        return path

    def test_legacy_replay_deletes_log_only_after_success(self):
        one, two = self.turn("one"), self.turn("two")
        path = self.write_legacy([one, two, replace(self.turn("unassigned"), person_id=None)])
        legacy = LegacyReplay(self.root, self.people)
        coordinator, worker = self.coordinator(legacy=legacy)
        coordinator.poll(0)
        self.assertTrue(path.exists())
        worker.respond(ProviderError("offline", True))
        coordinator.poll(1)
        self.assertTrue(path.exists())
        coordinator.poll(3)
        worker.respond((self.proposal("one", "two"),))
        coordinator.poll(4)
        self.assertFalse(path.exists())
        self.assertEqual(self.people.get(self.person.id).name, "Jon")
        self.assertNotIn("unassigned", self.context.people[self.person.id]["evidence"])

    def test_legacy_facts_keep_source_text_and_unassigned_is_not_promoted(self):
        one = self.turn("one", text="I study physics.")
        path = self.write_legacy([one, replace(self.turn("unknown"), person_id=None)])
        self.context.path.write_text(json.dumps({"version": 1, "people": {self.person.id: {
            "facts": [{"text": "Studies physics", "evidence_ids": ["one"]}], "processed_event_ids": ["one"],
        }}}))
        self.context = PersonContextStore(self.root)
        coordinator, worker = self.coordinator(legacy=LegacyReplay(self.root, self.people))
        coordinator.poll(0)
        self.assertFalse(worker.requests)
        self.assertFalse(path.exists())
        self.assertEqual(self.context.people[self.person.id]["evidence"]["one"]["text"], "I study physics.")
        self.assertIsNone(next(turn for turn in coordinator.conversation if turn.turn_id == "unknown").person_id)

    def test_failed_migration_and_concurrent_log_changes_preserve_log(self):
        path = self.write_legacy([self.turn("one")])
        coordinator, worker = self.coordinator(legacy=LegacyReplay(self.root, self.people))
        coordinator.poll(0)
        worker.respond(ProviderError("forbidden", False))
        coordinator.poll(1)
        self.assertTrue(path.exists())
        self.assertEqual(coordinator.close(), 0)  # Legacy text remains on disk.
        path = self.write_legacy([replace(self.turn("unknown"), person_id=None)])
        legacy = LegacyReplay(self.root, self.people)
        path.write_text(path.read_text() + "\n")
        coordinator, _ = self.coordinator(legacy=legacy)
        coordinator.poll(0)
        self.assertTrue(path.exists())
        self.assertTrue(coordinator.migration_failed)


if __name__ == "__main__":
    unittest.main()
