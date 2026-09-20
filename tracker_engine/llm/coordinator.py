"""Trigger logic for Gemini analysis — background thread and name/fact assignment.

Runs Gemini analysis in the background and applies names and facts directly
to Memory and GraphDB.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..memory import Memory
from ..storage import PersonStore, StoreError, person_id_to_node_id
from backend.graph_lib.handlers.graph_db import GraphDB
from backend.graph_lib.handlers.graph_agent_handler import GraphAgent
from backend.graph_lib.handlers.models import GraphNode


@dataclass
class Proposal:
    """What Gemini extracted for one person from a batch of speech turns."""
    person_id: str
    name: str | None = None
    facts: list[str] = field(default_factory=list)


class GeminiCoordinator:
    """Runs Gemini analysis in the background and updates Memory + GraphDB."""

    _MIN_CALL_INTERVAL = 5.0    # seconds between Gemini API requests
    _MAX_BATCH_SIZE = 4         # max turns to accumulate before forcing a call

    def __init__(
        self,
        memory: Memory,
        store: PersonStore,
        graph_db: GraphDB | None = None,
        api_key: str | None = None,
    ) -> None:
        self._memory = memory
        self._store = store
        self._graph_db = graph_db
        if graph_db is not None and api_key:
            self._graph_agent = GraphAgent(graph_db, api_key)
        else:
            self._graph_agent = None

        self._queue: queue.Queue[list] = queue.Queue(maxsize=128)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._pending: list = []
        self._last_call_at = 0.0
        self.status = "Idle"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        discarded = len(self._pending)
        while True:
            try:
                discarded += len(self._queue.get_nowait())
            except queue.Empty:
                break
        print(f"[Gemini] Coordinator stopped. Discarded {discarded} pending turns.", flush=True)

    # ------------------------------------------------------------------
    # Called from main loop (thread-safe)
    # ------------------------------------------------------------------

    def submit(self, turns: list) -> None:
        """Enqueue a batch of SpeechTurns for Gemini analysis."""
        if turns:
            try:
                self._queue.put_nowait(turns)
            except queue.Full:
                pass

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

            # Keep pending bounded to last 12 turns
            if len(self._pending) > 12:
                self._pending = self._pending[-12:]

            if not self._pending:
                continue

            now = time.perf_counter()
            time_since_last = now - self._last_call_at

            # Trigger every 5s when there is speech, or immediately on batch
            has_batch = len(self._pending) >= self._MAX_BATCH_SIZE
            has_elapsed = time_since_last >= self._MIN_CALL_INTERVAL

            if has_batch or has_elapsed:
                batch = list(self._pending)
                self._pending.clear()
                self._last_call_at = now
                try:
                    self._process(batch)
                except Exception as exc:
                    print(f"[Gemini] Unexpected worker error: {exc}", flush=True)

    def _process(self, turns: list) -> None:
        # Only process participants who actually spoke in this batch of turns
        speaking_pids = {t.person_id for t in turns if t.person_id}
        if not speaking_pids:
            return

        all_participants = self._memory.participants()
        active_participants = {
            pid: all_participants.get(pid)
            for pid in speaking_pids
            if pid in all_participants
        }
        if not active_participants:
            return

        attributed = [t for t in turns if t.person_id in active_participants]
        if not attributed:
            return

        if not self._graph_agent:
            self.status = "No GraphAgent available."
            return

        try:
            raw_proposals = self._graph_agent.analyze_identity(attributed, active_participants)
            proposals: list[Proposal] = []
            for item in raw_proposals:
                pid = item.get("person_id", "")
                if pid not in active_participants:
                    continue
                name = item.get("name")
                if isinstance(name, str):
                    name = name.strip() or None
                facts = [f.strip() for f in item.get("facts", []) if isinstance(f, str) and f.strip()]
                proposals.append(Proposal(person_id=pid, name=name, facts=facts))
        except Exception as exc:
            self.status = f"Gemini error: {exc}"
            print(f"[Gemini] Error: {exc}", flush=True)
            return

        self._apply(proposals)

    def _apply(self, proposals: list[Proposal]) -> None:
        """Directly update Memory and GraphDB only when there are actual changes."""
        for proposal in proposals:
            pid = proposal.person_id
            tracked = self._memory.get(pid)
            if tracked is None:
                continue

            changed = False

            # 1. Add facts to memory
            for fact in proposal.facts:
                if fact and fact not in tracked.facts:
                    self._memory.add_fact(pid, fact)
                    print(f"[Gemini] Fact for {pid}: {fact}", flush=True)
                    changed = True

            # 2. Update name in memory if provided
            if proposal.name:
                new_name = proposal.name.strip()
                if new_name and (not tracked.name or tracked.name.casefold() != new_name.casefold()):
                    self._memory.assign_name(pid, new_name)
                    self.status = f"Named {pid}: {new_name}"
                    print(f"[Gemini] {self.status}", flush=True)
                    changed = True

            # 3. Persist directly to Graph DB node ONLY if something changed
            if changed and self._graph_db is not None:
                nid = person_id_to_node_id(pid)
                existing = self._graph_db.get_node(nid)
                node_name = self._memory.label(pid)
                final_name = node_name if not node_name.startswith("person_") and not node_name.startswith("Seen before") else (existing.name if existing else "")
                
                all_facts = list(tracked.facts)
                desc = "\n".join(all_facts) if all_facts else (existing.description if existing else "")

                try:
                    self._graph_db.add_node(GraphNode(
                        node_id=nid,
                        name=final_name,
                        description=desc,
                    ))
                    print(f"[Gemini] Synced node #{nid} -> name='{final_name}'", flush=True)
                except Exception as exc:
                    print(f"[Gemini] Graph sync error for {pid}: {exc}", flush=True)
