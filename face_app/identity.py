"""Direct Gemini handoff; worker requests never mutate the person stores."""

from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict, deque

from .context import AnalysisRequest, ContextError, ProviderError
from .storage import StoreError


class AnalysisWorker:
    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.requests = queue.Queue(maxsize=1)
        self.completed = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, request):
        self.requests.put_nowait(request)

    def _run(self):
        try:
            while not self.stop.is_set():
                try:
                    request = self.requests.get(timeout=.2)
                except queue.Empty:
                    continue
                try:
                    outcome = self.analyzer.analyze(request)
                except Exception as exc:
                    outcome = exc
                if not self.stop.is_set():
                    self.completed.put((request, outcome))
        finally:
            self.analyzer.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)


class IdentityCoordinator:
    """Called on the camera thread; pending text and recent dialogue stay in memory."""

    def __init__(self, analyzer, context, people, legacy=None, *, worker=None, capacity=128, unavailable=None):
        self.context, self.people = context, people
        self.capacity = capacity
        self.pending = OrderedDict()
        self.conversation = deque(maxlen=30)
        self.seen = OrderedDict()
        self.notices = deque(maxlen=40)
        self.legacy = legacy
        self.legacy_queue = deque()
        self.paused = analyzer is None and worker is None
        if not self.paused and legacy is not None and not legacy.finished:
            context.migrate_sources(legacy.turns)
            self.conversation.extend(legacy.turns[-30:])
            self.legacy_queue.extend(turn for turn in legacy.turns if turn.person_id and turn.turn_id not in context.legacy_processed)
        self.worker = worker or (AnalysisWorker(analyzer) if analyzer is not None else None)
        self.active = None
        self.retry_request = None
        self.retry_at = 0.0
        self.attempt = 0
        self.status = unavailable or ("Gemini unavailable; speech is pending in memory." if self.paused else "Gemini ready; waiting for attributed speech.")
        self.notices.append(self.status)
        self.migration_failed = False

    def submit(self, turns):
        accepted = 0
        for turn in turns:
            if turn.turn_id in self.seen or turn.turn_id in self.pending:
                continue
            if turn.person_id and len(self.pending) >= self.capacity:
                self.notices.append("Gemini queue is full; new attributed speech was dropped.")
                continue
            self.seen[turn.turn_id] = None
            if len(self.seen) > 2048:
                self.seen.popitem(last=False)
            self.conversation = deque((item for item in self.conversation if item.turn_id != turn.turn_id), maxlen=30)
            self.conversation.append(turn)
            if turn.person_id:
                self.pending[turn.turn_id] = turn
            accepted += 1
        return accepted

    def _failure(self, request, error, now):
        retryable = isinstance(error, OSError) or (isinstance(error, ProviderError) and error.retryable)
        if retryable:
            delay = min(60, 2 ** min(self.attempt + 1, 6))
            self.attempt += 1
            self.retry_at, self.retry_request = now + delay, request
            self.status = f"Gemini retry in {delay}s: {error}"
        else:
            self.paused = True
            self.status = f"Gemini unavailable; restart after fixing the problem: {error}"
        self.notices.append(self.status)

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        try:
            if self.worker is None:
                raise queue.Empty
            request, outcome = self.worker.completed.get_nowait()
        except queue.Empty:
            pass
        else:
            self.active = None
            if isinstance(outcome, Exception):
                self._failure(request, outcome, now)
            else:
                try:
                    messages = self.context.apply(request, outcome, self.people)
                    if self.legacy is not None and not self.legacy.finished:
                        self.context.acknowledge_legacy(
                            turn.turn_id for turn in request.turns if turn.turn_id in self.legacy.eligible_ids
                        )
                except (ContextError, StoreError, OSError) as exc:
                    self._failure(request, exc, now)
                else:
                    for turn in request.turns:
                        self.pending.pop(turn.turn_id, None)
                    self.retry_request, self.attempt = None, 0
                    self.status = messages[-1]
                    self.notices.extend(messages)

        while self.legacy_queue and len(self.pending) < self.capacity:
            self.submit([self.legacy_queue.popleft()])
        if self.legacy is not None and not self.legacy.finished and not self.migration_failed and not self.paused:
            try:
                if self.legacy.finish(self.context):
                    self.notices.append("Legacy speech migrated; temporary transcript log removed.")
            except (ContextError, OSError) as exc:
                self.migration_failed = True
                self.notices.append(f"Legacy migration incomplete: {exc}")
        if self.paused or self.active is not None or not self.pending or now < self.retry_at:
            return
        request = self.retry_request or AnalysisRequest(
            tuple(list(self.pending.values())[:30]), tuple(self.conversation),
            {person.id: person.name for person in self.people.people}, self.context.snapshot(),
        )
        self.active = request
        self.status = "Gemini processing identity evidence."
        self.worker.submit(request)

    def close(self):
        if self.worker is not None:
            self.worker.close()
        legacy_ids = self.legacy.eligible_ids if self.legacy is not None and not self.legacy.finished else set()
        return sum(key not in legacy_ids for key in self.pending)
