"""Trigger logic for Gemini analysis — background thread, corroboration, name assignment.

This module owns:
  - The background worker thread that calls GeminiAnalyzer
  - Corroboration: a name must appear in >= 2 distinct audio clips before it's saved
  - Writing results back to Memory and PersonStore

The main loop only calls coordinator.submit(turns). Everything else is autonomous.
"""

from __future__ import annotations

import os
import queue
import threading
import time

from typing import TYPE_CHECKING

from ..memory import Memory
from ..storage import PersonStore, StoreError, person_id_to_node_id
from .analyzer import AnalyzerError, GeminiAnalyzer, Proposal

if TYPE_CHECKING:
    from backend.graph_lib.handlers.graph_db import GraphDB


_IDENTITY_CUES = (
    "name", "i'm ", "i am ", "call me", "this is", "meet ", "introduce", "i work",
    "i like", "i love", "years old", "from ", "my name"
)


class GeminiCoordinator:
    """Runs Gemini analysis in the background and applies results to Memory + Storage.

    Usage:
        coordinator = GeminiCoordinator(analyzer, memory, store)
        coordinator.start()
        ...
        coordinator.submit(turns)        # call from main loop
        ...
        coordinator.stop()              # call on shutdown
    """

    _MIN_CALL_INTERVAL = 6.0    # seconds between Gemini API requests (rate limiting)
    _MAX_BATCH_SIZE = 5         # max turns to accumulate before forcing a call

    def __init__(
        self,
        analyzer: GeminiAnalyzer,
        memory: Memory,
        store: PersonStore,
        graph_db: "GraphDB | None" = None,
    ) -> None:
        self._analyzer = analyzer
        self._memory = memory
        self._store = store
        self._graph_db = graph_db
        self._contexts: dict[str, dict] = {}
        self._queue: queue.Queue[list] = queue.Queue(maxsize=128)     # list[SpeechTurn]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._pending: list = []                                       # list[SpeechTurn]
        self._last_call_at = 0.0
        self.status = "Idle"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=25)
        discarded = len(self._pending)
        while True:
            try:
                discarded += len(self._queue.get_nowait())
            except queue.Empty:
                break
        print(f"[Gemini] Discarded {discarded} pending speech turns on exit.", flush=True)

    # ------------------------------------------------------------------
    # Called from main loop (thread-safe)
    # ------------------------------------------------------------------

    def submit(self, turns: list) -> None:
        """Enqueue a batch of SpeechTurns for Gemini analysis."""
        if turns:
            try:
                self._queue.put_nowait(turns)
            except queue.Full:
                print(f"[Gemini] Queue full; discarded {len(turns)} speech turns.", flush=True)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                turns = self._queue.get(timeout=0.5)
            except queue.Empty:
                turns = None

            if turns:
                self._pending.extend(turns)

            # Keep pending bounded to last 15 turns
            if len(self._pending) > 15:
                self._pending = self._pending[-15:]

            if not self._pending:
                continue

            # Check if we should trigger Gemini
            now = time.perf_counter()
            time_since_last = now - self._last_call_at
            if time_since_last < self._MIN_CALL_INTERVAL:
                continue

            has_cue = any(
                any(cue in t.text.lower() for cue in _IDENTITY_CUES)
                for t in self._pending
            )
            has_batch = len(self._pending) >= self._MAX_BATCH_SIZE

            if has_cue or has_batch:
                batch = list(self._pending)
                self._pending.clear()
                self._last_call_at = now
                self._process(batch)

    def _process(self, turns: list) -> None:
        participants = self._memory.participants()
        if not participants:
            return

        # Only send turns that are attributed to known people
        attributed = [t for t in turns if t.person_id in participants]
        if not attributed:
            return

        try:
            proposals = self._analyzer.analyze(attributed, participants)
        except AnalyzerError as exc:
            self.status = f"Gemini error: {exc}"
            print(f"[Gemini] Error: {exc}", flush=True)
            return

        try:
            self._apply(proposals, attributed)
        except StoreError as exc:
            self.status = f"Could not save person evidence: {exc}"
            print(f"[Gemini] {self.status}", flush=True)

    def _apply(self, proposals: list[Proposal], turns: list) -> None:
        """Apply Gemini proposals to Memory and PersonStore (called in bg thread)."""
        evidence = {t.turn_id: {"turn_id": t.turn_id, "clip_id": t.clip_id,
                                "person_id": t.person_id, "text": t.text}
                    for t in turns}
        for proposal in proposals:
            pid = proposal.person_id
            tracked = self._memory.get(pid)
            if tracked is None:
                continue
            context = self._contexts.setdefault(pid, {})
            current_name = tracked.name

            def cited(ids):
                if not isinstance(ids, list) or not ids:
                    return []
                if any(not isinstance(i, str) or i not in evidence
                       or evidence[i]["person_id"] != pid for i in ids):
                    return []
                return [evidence[i] for i in dict.fromkeys(ids)]

            # Save only facts with citations attributed to this stable person ID.
            for fact in proposal.facts:
                support = cited(proposal.fact_evidence_ids.get(fact, []))
                if not support:
                    continue
                context.setdefault("fact_evidence", {})[fact] = support
                self._memory.add_fact(pid, fact)
                print(f"[Gemini] Fact for {pid}: {fact}", flush=True)

            if not proposal.name:
                continue
            support = cited(proposal.name_evidence_ids)
            if not support:
                continue
            key = proposal.name.strip().casefold()
            if current_name and current_name.casefold() == key:
                continue

            # Name lives in Memory and the graph only — not in MongoDB.
            self._memory.assign_name(pid, proposal.name)

            # Mirror the confirmed name into the optional graph DB
            if self._graph_db is not None:
                node_id = person_id_to_node_id(pid)
                try:
                    node = self._graph_db.get_node(node_id)
                    if node is not None:
                        from backend.graph_lib.handlers.models import GraphNode
                        updated = GraphNode(
                            node_id=node.node_id,
                            name=proposal.name,
                            description=node.description,
                        )
                        self._graph_db.add_node(updated)
                        print(f"[Gemini] Saved name '{proposal.name}' → graph node #{node_id}", flush=True)
                except Exception as exc:
                    print(f"[Gemini] Graph name save failed for {pid}: {exc}", flush=True)

            self.status = f"Named {pid}: {proposal.name}"
            print(f"[Gemini] {self.status}", flush=True)
