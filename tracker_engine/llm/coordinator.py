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
from collections import defaultdict

from typing import TYPE_CHECKING

from ..memory import Memory
from ..storage import PersonStore, StoreError, person_id_to_node_id
from .analyzer import AnalyzerError, GeminiAnalyzer, Proposal

if TYPE_CHECKING:
    from graph_lib.db import GraphDB


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
        self._queue: queue.Queue[list] = queue.Queue()     # list[SpeechTurn]
        self._pending: list = []
        self._last_call_at: float = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="GeminiCoordinator"
        )
        # Corroboration: person_id → set of clip_ids where Gemini proposed the name
        self._name_clips: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.status = "Gemini coordinator ready."

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put([])   # unblock the worker if it's waiting
        self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Called from main loop (thread-safe)
    # ------------------------------------------------------------------

    def submit(self, turns: list) -> None:
        """Enqueue a batch of SpeechTurns for Gemini analysis."""
        if turns:
            self._queue.put(turns)

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

        self._apply(proposals, attributed)

    def _apply(self, proposals: list[Proposal], turns: list) -> None:
        """Apply Gemini proposals to Memory and PersonStore (called in bg thread)."""
        all_clips = {t.clip_id for t in turns}
        for proposal in proposals:
            pid = proposal.person_id

            # --- Facts ---
            for fact in proposal.facts:
                self._memory.add_fact(pid, fact)
                print(f"[Gemini] Fact for {pid}: {fact}", flush=True)

            # --- Name corroboration ---
            if not proposal.name:
                continue

            key = proposal.name.strip().casefold()
            # Find clip_ids from this batch that cite or attribute this person
            person_clips = {t.clip_id for t in turns if t.person_id == pid}
            clip_ids = person_clips if person_clips else all_clips
            self._name_clips[pid][key].update(clip_ids)

            confirmed_clips = self._name_clips[pid][key]
            min_clips = int(os.getenv("REQUIRED_NAME_CLIPS", "1"))
            if len(confirmed_clips) < min_clips:
                count = len(confirmed_clips)
                self.status = f"Name candidate '{proposal.name}' for {pid}: {count}/{min_clips} clips."
                print(f"[Gemini] {self.status}", flush=True)
                continue

            # Assign the name immediately
            current_name = self._memory.get(pid).name if self._memory.get(pid) else None
            if current_name and current_name.casefold() == key:
                continue  # already assigned this name

            self._memory.assign_name(pid, proposal.name)

            # Write name to graph DB (authoritative source)
            if self._graph_db is not None:
                node_id = person_id_to_node_id(pid)
                try:
                    node = self._graph_db.get_node(node_id)
                    if node is not None:
                        from graph_lib.models import GraphNode
                        updated = GraphNode(
                            node_id=node.node_id,
                            name=proposal.name,
                            description=node.description,
                        )
                        self._graph_db.add_node(updated)
                        print(f"[Gemini] Saved name '{proposal.name}' → graph node #{node_id}", flush=True)
                except Exception as exc:
                    print(f"[Gemini] Graph name save failed for {pid}: {exc}", flush=True)
            else:
                print(f"[Gemini] No graph DB connected — name '{proposal.name}' cached in memory only.", flush=True)

            # Reset corroboration for this person (clean slate for future corrections)
            self._name_clips[pid] = defaultdict(set)
            self.status = f"Named {pid}: {proposal.name}"
            print(f"[Gemini] {self.status}", flush=True)
