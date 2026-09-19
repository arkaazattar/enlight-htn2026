"""Evidence survives restarts and automatic naming uses the MongoDB repository."""

from types import SimpleNamespace
import unittest

import test_mongodb_people as fixtures
from tracker_engine.llm.analyzer import Proposal
from tracker_engine.llm.coordinator import GeminiCoordinator
from tracker_engine.memory import Memory
from tracker_engine.storage import PersonStore


class TrackerPersistenceTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the repository fixture, without inheriting its test cases.
        self.repository = fixtures.MongoPeopleTests.repository(self)
        self.store = PersonStore(self.repository.root, self.repository)
        self.pid = self.store.enroll(fixtures.PNG)
        self.other = self.store.enroll(fixtures.PNG)
        self.memory = Memory()
        self.memory.add(self.pid)
        self.memory.add(self.other)
        self.coordinator = self.restart()

    def restart(self):
        return GeminiCoordinator(None, self.memory, self.store)

    def turn(self, turn_id, clip_id, pid=None):
        return SimpleNamespace(turn_id=turn_id, clip_id=clip_id,
                               person_id=pid or self.pid, text="My name is Ada")

    def test_two_distinct_clips_required_across_restart(self):
        self.coordinator._apply([Proposal(self.pid, "Ada", [], ["t1", "t2"])],
                                [self.turn("t1", "clip1"), self.turn("t2", "clip1")])
        self.assertIsNone(self.store.get(self.pid).name)
        self.coordinator = self.restart()
        self.coordinator._apply([Proposal(self.pid, "Ada", [], ["t3"])],
                                [self.turn("t3", "clip2")])
        person = self.store.get(self.pid)
        self.assertEqual(person.name, "Ada")
        self.assertEqual(person.image_paths, ["faces/Ada.png"])
        self.assertEqual(self.memory.get(self.pid).name, "Ada")
        self.assertEqual(len(person.context["name_evidence"]["evidence"]), 3)

    def test_wrong_person_or_missing_citations_never_save(self):
        self.coordinator._apply([
            Proposal(self.pid, "Ada", ["Studies physics"], ["other"], {"Studies physics": ["other"]}),
            Proposal(self.pid, "Ada", ["Studies physics"]),
        ], [self.turn("other", "clip1", self.other)])
        person = self.store.get(self.pid)
        self.assertIsNone(person.name)
        self.assertEqual(person.facts, ())
        self.assertEqual(person.context, {})

    def test_fact_and_support_persist(self):
        self.coordinator._apply([Proposal(self.pid, None, ["Studies physics"],
                                         fact_evidence_ids={"Studies physics": ["t1"]})],
                                [self.turn("t1", "clip1")])
        person = self.store.get(self.pid)
        self.assertEqual(person.facts, ("Studies physics",))
        self.assertEqual(person.context["fact_evidence"]["Studies physics"][0]["person_id"], self.pid)

    def test_name_correction_requires_explicit_correction_citation(self):
        self.store.assign_name(self.pid, "Augusta")
        turns = [self.turn("t1", "clip1"), self.turn("t2", "clip2")]
        self.coordinator._apply([Proposal(self.pid, "Ada", [], ["t1", "t2"])], turns)
        self.assertEqual(self.store.get(self.pid).name, "Augusta")
        self.coordinator = self.restart()
        self.coordinator._apply([Proposal(self.pid, "Ada", [], ["t3"], correction_ids=["t3"])],
                                [self.turn("t3", "clip3")])
        self.assertEqual(self.store.get(self.pid).name, "Ada")
        self.assertFalse((self.repository.root / "faces/Augusta.png").exists())


if __name__ == "__main__":
    unittest.main()
