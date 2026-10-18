"""Runs: one active at a time, outliving the frontend (design.md L4).

A run is an `asyncio` task plus an in-memory event buffer. The buffer is the
whole persistence story: a run that finishes leaves its events, and they are
dropped shortly after. Nothing goes to disk, because the *messages* are already
in Strands' snapshot -- an event log would be a second copy of the same thing
with a schema to keep in sync.

Consequences, all deliberate:

* Closing the browser does not touch a run. The task belongs to the server.
* A reopened frontend resumes with `GET /runs/{id}/events?after=<n>` and gets
  everything it missed, then live events. No gaps, no duplicates.
* A backend crash loses the partial text. The turn becomes `interrupted` and
  retry is the recovery. That is the price of no event log, and it is the right
  trade: the answer is regenerable, an event log is not.
* One run at a time; a second start returns 409.
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

        `timings` arrive with every generated token; they are folded every time
        but emitted at most four times a second, which is as fast as a context
        meter can usefully move and keeps the event buffer small.
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
        elif kind in ("call_start", "model_retry"):
            self.emit(event)

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
        """Mark a run finished and free the slot."""
        if self._active == run.id:
            self._active = None

    # ------------------------------------------------------------- cancel --

    def cancel(self, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        if run is None or run.done:
            return run
        run.cancel.set()
        if run.agent is not None:
            # The documented path. Also sets the signal the model watches.
            try:
                run.agent.cancel()
            except Exception:  # noqa: BLE001
                logger.exception("agent.cancel() failed")
        return run

    # ------------------------------------------------------------- stream --

    async def stream(self, run: Run, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Replay from `after`, then follow live.

        This is what makes a reloaded frontend work: the client sends the last
        sequence number it saw and receives everything after it, whether that
        happened while it was closed or is happening now.
        """
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
