"""Runs: one active at a time, outliving the frontend (server/AGENTS.md).

A run is an `asyncio` task plus an in-memory event buffer, dropped a few
minutes after the run ends. Nothing goes to disk: the messages are already in
Strands' snapshot, and an event log would be a second copy with its own schema.
The price is that a backend crash loses the partial text; the turn becomes
`interrupted` and retry recovers it.

A reopened frontend resumes with `GET /runs/{id}/events?after=<n>` and gets
everything it missed, then live events.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from server.transcript import Transcript, stats_from_timings

logger = logging.getLogger(__name__)


class RunConflict(Exception):
    """A run is already active. The caller turns this into a 409."""


@dataclass
class Run:
    id: str
    chat_id: str
    turn_id: str
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    #: Set by cancel(); the run loop checks it between events.
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    agent: Any = None
    #: Subscribers currently reading the stream, so a finish can wake them.
    waiters: list[asyncio.Event] = field(default_factory=list)
    #: What the UI shows for this turn, folded from the same events it streams.
    transcript: Transcript = field(default_factory=lambda: Transcript(0))
    _last_stats: float = 0.0
    #: Questions waiting for the user: approval id -> future of the decision.
    approvals: dict[str, asyncio.Future] = field(default_factory=dict)
    #: Work waiting on the client (the extension's page operations): call id -> future.
    calls: dict[str, asyncio.Future] = field(default_factory=dict)
    #: The page the extension attached to this turn ({"url", "title"}), if any.
    page: dict[str, Any] | None = None
    #: Page content has entered the turn: the tool policy asks before risky tools.
    tainted: bool = False
    #: The chat workspace when the run began: `path -> (size, mtime_ns)`.
    workspace_before: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.status in {"completed", "failed", "cancelled", "interrupted"}

    def emit(self, event: dict[str, Any]) -> int:
        """Append one event and return its sequence number.

        The sequence number is what `after=<n>` resumes from, so it is assigned
        here and nowhere else.
        """
        self.events.append({"seq": len(self.events), **event})
        self.transcript.fold(event)
        self.wake()
        return len(self.events) - 1

    def observe(self, event: dict[str, Any]) -> None:
        """The model's and the retry strategy's side channel into the run.

        `timings` arrive with every generated token. They are always folded but
        emitted at most four times a second, which keeps the buffer small.
        """
        kind = event.get("type")
        if kind == "timings":
            stats = {"type": "stats", **stats_from_timings(event)}
            now = time.monotonic()
            if now - self._last_stats >= 0.25:
                self._last_stats = now
                self.emit(stats)
            else:
                self.transcript.fold(stats)
        elif kind in ("call_start", "model_retry", "resumed"):
            self.emit(event)

    async def request_approval(self, kind: str, detail: dict[str, Any], timeout: float) -> str:
        """Ask the user, and wait. Returns "allowed", "denied" or "expired".

        The question and its answer are both events, so a reloaded page shows
        the pending card, and the transcript keeps what was decided.
        """
        approval_id = uuid.uuid4().hex[:12]
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.approvals[approval_id] = future
        self.emit({"type": "approval_request", "id": approval_id, "kind": kind, **detail,
                   "timeout": timeout, "expires_at": int((time.time() + timeout) * 1000)})
        try:
            decision = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            decision = "expired"
        finally:
            self.approvals.pop(approval_id, None)
        self.emit({"type": "approval_result", "id": approval_id, "decision": decision})
        return decision

    def answer(self, approval_id: str, allow: bool) -> bool:
        future = self.approvals.get(approval_id)
        if future is None or future.done():
            return False
        future.set_result("allowed" if allow else "denied")
        return True

    async def client_call(self, op: str, args: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """Ask the client to do something and wait for its result.

        The same round trip as an approval: an event out, a POST back
        (`/runs/{id}/calls/{call_id}`), a future in between. A call nobody
        answers in time, or one cut short by a cancel, returns an error the
        tool passes to the model.
        """
        call_id = uuid.uuid4().hex[:12]
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.calls[call_id] = future
        self.emit({"type": "client_call", "id": call_id, "op": op, "args": args})
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return {"error": "the browser did not answer; is the Atlas side panel still open on that page?"}
        finally:
            self.calls.pop(call_id, None)

    def resolve_call(self, call_id: str, result: dict[str, Any]) -> bool:
        future = self.calls.get(call_id)
        if future is None or future.done():
            return False
        future.set_result(result)
        return True

    def deny_all(self) -> None:
        for future in list(self.approvals.values()):
            if not future.done():
                future.set_result("denied")
        for future in list(self.calls.values()):
            if not future.done():
                future.set_result({"error": "the run was cancelled"})

    def wake(self) -> None:
        for waiter in self.waiters:
            waiter.set()

    def finish(self, status: str, error: str | None = None) -> None:
        if self.done:
            return
        self.status = status
        self.error = error
        self.finished_at = time.time()
        # The last throttled stats may have been folded but never sent.
        self.emit({"type": "stats", **{k: v for k, v in self.transcript.final_stats().items()}})
        self.emit({"type": "error", "status": status, "message": error} if error
                  else {"type": "done", "status": status})
        self.wake()


class RunManager:
    """Owns the active run and the short-lived run history."""

    def __init__(self, *, keep_after_s: float = 300.0) -> None:
        self._runs: dict[str, Run] = {}
        self._active: str | None = None
        self._keep_after_s = keep_after_s

    # ------------------------------------------------------------- lookup --

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def active(self) -> Run | None:
        return self._runs.get(self._active) if self._active else None

    def active_for_chat(self, chat_id: str) -> Run | None:
        run = self.active()
        return run if run and run.chat_id == chat_id else None

    # -------------------------------------------------------------- start --

    def start(self, chat_id: str, turn_id: str, *, context_size: int = 0) -> Run:
        if self.active() is not None:
            raise RunConflict("a run is already active")
        self.sweep()
        run = Run(id=uuid.uuid4().hex, chat_id=chat_id, turn_id=turn_id,
                  transcript=Transcript(context_size))
        self._runs[run.id] = run
        self._active = run.id
        return run

    def ensure_available(self) -> None:
        """Fail before a route mutates the chat tree for a rejected start."""
        if self.active() is not None:
            raise RunConflict("a run is already active")

    def adopt(self, run: Run) -> None:
        """Free the active slot once a run has ended."""
        if self._active == run.id:
            self._active = None

    # ------------------------------------------------------------- cancel --

    def cancel(self, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        if run is None or run.done:
            return run
        run.cancel.set()
        # A pending question would otherwise hold the run until it times out.
        run.deny_all()
        if run.agent is not None:
            # Strands' own cancel; it also sets the signal the model watches.
            try:
                run.agent.cancel()
            except Exception:  # noqa: BLE001
                logger.exception("agent.cancel() failed")
        return run

    # ------------------------------------------------------------- stream --

    async def stream(self, run: Run, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Replay from `after` (the first seq the client has not seen), then follow live."""
        index = max(0, after)
        while True:
            while index < len(run.events):
                yield run.events[index]
                index += 1
            if run.done:
                # One final drain: a finish event may have landed after the
                # loop above checked.
                while index < len(run.events):
                    yield run.events[index]
                    index += 1
                return
            waiter = asyncio.Event()
            run.waiters.append(waiter)
            try:
                await asyncio.wait_for(waiter.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass  # a periodic wake, so a client never hangs indefinitely
            finally:
                if waiter in run.waiters:
                    run.waiters.remove(waiter)

    # -------------------------------------------------------------- sweep --

    def sweep(self) -> None:
        """Drop finished runs whose buffer nobody is reading any more."""
        cutoff = time.time() - self._keep_after_s
        for run_id, run in list(self._runs.items()):
            if run.done and (run.finished_at or 0) < cutoff and not run.waiters:
                del self._runs[run_id]


__all__ = ["Run", "RunConflict", "RunManager"]
