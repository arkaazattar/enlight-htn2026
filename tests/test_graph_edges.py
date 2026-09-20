"""Every graph node can reach every other node in either direction."""

import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch

from backend.graph_lib.handlers.graph_db import GraphDB
from backend.graph_lib.handlers.graph_agent_handler import GraphAgent
from backend.graph_lib.handlers import graph_agent_handler
from backend.graph_lib.handlers.models import GraphEdge, GraphNode
from backend.graph_lib.handlers.traversal import _build_graph
from tracker_engine.llm.coordinator import GeminiCoordinator, Proposal
from tracker_engine.memory import Memory


class FakeNodes:
    def __init__(self):
        self.docs = {}

    def find(self, query=None, *_args):
        ids = query.get("node_id", {}).get("$in", self.docs) if query else self.docs
        return [{"node_id": node_id} for node_id in self.docs if node_id in ids]

    def find_one_and_replace(self, query, document, **_kwargs):
        self.docs[query["node_id"]] = document
        return document


class FakeEdges:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, **_kwargs):
        key = query["from_node_id"], query["to_node_id"]
        self.docs.setdefault(key, update["$setOnInsert"].copy())

    def find(self, query=None, **_kwargs):
        docs = [dict(from_node_id=a, to_node_id=b, _id=(a, b), **value)
                for (a, b), value in self.docs.items()]
        if query and "$expr" in query:
            return [doc for doc in docs if doc["from_node_id"] > doc["to_node_id"]]
        return docs

    def delete_one(self, query):
        self.docs.pop(query["_id"])

    def find_one(self, query):
        key = query["from_node_id"], query["to_node_id"]
        value = self.docs.get(key)
        return dict(from_node_id=key[0], to_node_id=key[1], **value) if value else None

    def find_one_and_replace(self, query, document, **_kwargs):
        key = query["from_node_id"], query["to_node_id"]
        self.docs[key] = {"probability": document["probability"],
                          "score_version": document["score_version"]}
        return document


class CompleteGraphTests(unittest.TestCase):
    def setUp(self):
        self.db = GraphDB.__new__(GraphDB)
        self.db._nodes = FakeNodes()
        self.db._edges = FakeEdges()

    def test_only_enrolled_nodes_connect_and_keep_existing_weights(self):
        for node_id in (1, 2, 3):
            self.db.add_node(GraphNode(node_id, str(node_id), ""))
        self.db.ensure_person_edges((1, 2))
        self.assertEqual(len(self.db._edges.docs), 1)
        self.assertNotIn((1, 1), self.db._edges.docs)

        self.db._edges.docs[(1, 2)]["probability"] = 0.8
        self.db.add_node(GraphNode(1, "updated", "new fact"))
        self.db.ensure_person_edges((1, 2))
        self.assertEqual(self.db._edges.docs[(1, 2)]["probability"], 0.8)
        self.assertEqual(len(self.db._edges.docs), 1)

    def test_backfill_connects_existing_nodes_without_resetting_scores(self):
        self.db._nodes.docs = {1: {}, 2: {}, 3: {}}
        self.db._edges.docs[(1, 2)] = {"probability": 0.4}
        self.db._edges.docs[(2, 1)] = {"probability": 0.7}
        self.db._migrate_directed_edges()
        self.db.ensure_person_edges((1, 2, 3))
        self.assertEqual(len(self.db._edges.docs), 3)
        self.assertEqual(self.db._edges.docs[(1, 2)]["probability"], 0.4)
        self.assertNotIn((2, 1), self.db._edges.docs)

    def test_reversed_lookup_and_write_use_one_pair(self):
        self.db.add_edge(GraphEdge(2, 1, 0.6, score_version=1))
        self.assertEqual(list(self.db._edges.docs), [(1, 2)])
        self.assertEqual(self.db.get_edge(2, 1).probability, 0.6)
        self.db.add_edge(GraphEdge(1, 2, 0.8, score_version=1))
        self.assertEqual(len(self.db._edges.docs), 1)

    def test_traversal_uses_an_undirected_graph(self):
        class ReadDB:
            def get_all_nodes(self):
                return [GraphNode(1, "Ada", "Guitar"), GraphNode(2, "Sam", "Drums")]

            def get_all_edges(self):
                return [GraphEdge(1, 2, 0.8, score_version=1)]

        graph = _build_graph(ReadDB())
        self.assertFalse(graph.is_directed())
        self.assertTrue(graph.has_edge(2, 1))

    def test_scoring_refreshes_each_direction_for_changed_node(self):
        class ScoreDB:
            def __init__(self):
                self.edges = [GraphEdge(1, 2, 0.0, score_version=2), GraphEdge(2, 3, 0.4)]
                self.saved = []

            def get_all_nodes(self):
                return [GraphNode(1, "Ada", "Guitar"), GraphNode(2, "Sam", "Drums"),
                        GraphNode(3, "Lee", "Piano")]

            def get_all_edges(self):
                return self.edges

            def add_edge(self, edge):
                self.saved.append(edge)

        db = ScoreDB()
        agent = GraphAgent.__new__(GraphAgent)
        agent.db = db
        calls = []
        agent._score_edge = lambda *args: calls.append(args) or 0.6
        agent.score_edges(1, unscored_only=True)
        self.assertEqual([(e.from_node_id, e.to_node_id, e.probability, e.score_version) for e in db.saved],
                         [(1, 2, 0.6, 3)])
        self.assertEqual(calls[0], ("Ada", "Guitar", "Sam", "Drums"))
        self.assertEqual(len(calls), 1)

    def test_scoring_waits_for_both_people_to_have_facts(self):
        class ScoreDB:
            def get_all_nodes(self):
                return [GraphNode(1, "Ada", "Guitar"), GraphNode(2, "Sam", "")]

            def get_all_edges(self):
                return [GraphEdge(1, 2, 0.0)]

            def add_edge(self, edge):
                raise AssertionError("Empty descriptions should not be scored")

        agent = GraphAgent.__new__(GraphAgent)
        agent.db = ScoreDB()
        agent._score_edge = lambda *_args: self.fail("Gemini should not be called")
        result = agent.score_edges(1, allowed_ids={1, 2})
        self.assertEqual(result["waiting_for_facts"], 1)

    def test_edge_worker_receives_fact_refresh(self):
        class FakeAgent:
            def __init__(self):
                self.calls = []
                self.refreshed = threading.Event()

            def score_edges(self, node_id=None, **kwargs):
                self.calls.append((node_id, kwargs))
                if node_id is not None:
                    self.refreshed.set()
                return {"pairs": 1, "scored": 1, "waiting_for_facts": 0}

        memory = Memory()
        store = SimpleNamespace(person_ids=["abcdef123456", "abcdef123457"])
        coordinator = GeminiCoordinator(memory, store)
        agent = FakeAgent()
        coordinator._graph_agent = agent
        coordinator.start()
        try:
            coordinator.score_node(int("abcdef123456", 16))
            self.assertTrue(agent.refreshed.wait(3))
            self.assertEqual(agent.calls[-1][0], int("abcdef123456", 16))
            self.assertEqual(agent.calls[-1][1]["allowed_ids"],
                             {int("abcdef123456", 16), int("abcdef123457", 16)})
        finally:
            coordinator.stop()

    def test_edge_requests_are_spaced_even_after_a_retry(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "test-model"
        agent._edge_min_interval = 15.0
        agent._next_edge_request_at = 0.0
        clock = [100.0]
        request_times = []

        def generate_content(**_kwargs):
            request_times.append(clock[0])
            if len(request_times) == 1:
                raise RuntimeError("rate limited")
            return SimpleNamespace(text="0.5")

        agent._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

        def sleep(seconds):
            clock[0] += seconds

        with patch.object(graph_agent_handler.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(graph_agent_handler.time, "sleep", side_effect=sleep):
            self.assertEqual(agent._call_gemini("edge", edge_scoring=True), "0.5")
            self.assertEqual(agent._call_gemini("next edge", edge_scoring=True), "0.5")

        self.assertEqual(request_times, [100.0, 115.0, 130.0])

    def test_daily_quota_error_stops_edge_retries(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "gemini-2.5-flash"
        agent._edge_min_interval = 15.0
        agent._next_edge_request_at = 0.0
        calls = []

        def generate_content(**_kwargs):
            calls.append(1)
            raise RuntimeError("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDayPerProjectPerModel-FreeTier")

        agent._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        with self.assertRaisesRegex(RuntimeError, "daily request quota exhausted"):
            agent._call_gemini("edge", edge_scoring=True)
        self.assertEqual(len(calls), 1)

    def test_edge_scoring_falls_back_and_remembers_daily_quota(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "gemini-2.5-flash"
        agent._edge_quota_exhausted_models = set()
        calls = []

        def call(_prompt, *, edge_scoring=False, model=None):
            calls.append(model)
            self.assertTrue(edge_scoring)
            if model == "gemini-2.5-flash":
                raise graph_agent_handler._DailyQuotaError("daily request quota exhausted")
            return "0.75"

        agent._call_gemini = call
        self.assertEqual(agent._score_edge("Ada", "Guitar", "Sam", "Drums"), 0.75)
        self.assertEqual(calls, ["gemini-2.5-flash", "gemini-3.6-flash"])
        self.assertEqual(agent._score_edge("Ada", "Guitar", "Lee", "Piano"), 0.75)
        self.assertEqual(calls[-1], "gemini-3.6-flash")
        self.assertEqual(calls.count("gemini-2.5-flash"), 1)

    def test_unrelated_people_get_a_low_positive_score(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "gemini-2.5-flash"
        agent._edge_quota_exhausted_models = set()
        agent._call_gemini = lambda *_args, **_kwargs: "0.0"
        self.assertEqual(
            agent._score_edge("Ada", "Long walks at the beach", "Sam", "Likes chicken"),
            0.1,
        )

    def test_shared_direct_interest_outweighs_unrelated_facts(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "gemini-2.5-flash"
        agent._edge_quota_exhausted_models = set()
        agent._call_gemini = lambda *_args, **_kwargs: "0.1"
        self.assertEqual(
            agent._score_edge(
                "Ada", "Likes tacos\nWas told it was Pakistan",
                "Sam", "likes tacos with beef\nAll his best friends were brown",
            ),
            0.6,
        )

    def test_friend_interest_does_not_count_as_persons_own_interest(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "gemini-2.5-flash"
        agent._edge_quota_exhausted_models = set()
        agent._call_gemini = lambda *_args, **_kwargs: "0.1"
        self.assertEqual(
            agent._score_edge("Ada", "Likes tacos", "Sam", "Has a friend who likes tacos"),
            0.1,
        )

    def test_shared_interest_floor_persists_when_gemini_is_unavailable(self):
        class ScoreDB:
            def __init__(self):
                self.saved = []

            def get_all_nodes(self):
                return [GraphNode(1, "Ada", "Likes tacos"),
                        GraphNode(2, "Sam", "likes tacos with beef")]

            def get_all_edges(self):
                return [GraphEdge(1, 2, 0.1, score_version=2)]

            def add_edge(self, edge):
                self.saved.append(edge)

        db = ScoreDB()
        agent = GraphAgent.__new__(GraphAgent)
        agent.db = db
        agent._score_edge = lambda *_args: (_ for _ in ()).throw(RuntimeError("quota"))
        with self.assertRaisesRegex(RuntimeError, "quota"):
            agent.score_edges(unscored_only=True)
        self.assertEqual([(e.probability, e.score_version) for e in db.saved], [(0.6, 2)])

    def test_all_failed_models_leave_edge_unscored(self):
        agent = GraphAgent.__new__(GraphAgent)
        agent.gemini_model = "gemini-2.5-flash"
        agent._edge_quota_exhausted_models = set(agent._model_candidates())
        with self.assertRaisesRegex(RuntimeError, "edge remains unscored"):
            agent._score_edge("Ada", "Guitar", "Sam", "Drums")

    def test_new_fact_queues_one_refresh_and_name_alone_does_not(self):
        class NodeDB:
            def __init__(self):
                self.nodes = {}

            def get_node(self, node_id):
                return self.nodes.get(node_id)

            def add_node(self, node):
                self.nodes[node.node_id] = node

        memory = Memory()
        memory.add("abcdef123456")
        db = NodeDB()
        coordinator = GeminiCoordinator(memory, object(), graph_db=db)
        coordinator._graph_agent = object()
        coordinator._apply([Proposal("abcdef123456", "Ada", ["Guitar", "Physics"])])
        self.assertEqual(coordinator._edge_queue.get_nowait(), int("abcdef123456", 16))
        self.assertTrue(coordinator._edge_queue.empty())
        coordinator._apply([Proposal("abcdef123456", "Augusta", [])])
        self.assertTrue(coordinator._edge_queue.empty())


if __name__ == "__main__":
    unittest.main()
