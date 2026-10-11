"""EventSink: the only writer of ``run_events`` (spec section 8).

Three jobs:

1. **Own the sequence.** ``seq`` is assigned by the database inside
   ``Repo.append_event``, so replay, SSE ids and reconnect dedupe all agree by
   construction.
2. **Coalesce deltas.** Token-by-token ``text_delta`` events would spend a
   database write and an SSE frame each. They are buffered and flushed every
   ~50 ms or ~200 characters, whichever comes first.
3. **Broadcast.** Fan out to every attached SSE client.

The ordering rule that is easy to get wrong: a buffered delta must be flushed
*before* any non-delta event is written. Otherwise ``tool_call_started`` would
take a lower ``seq`` than the ``text_delta`` that preceded it, and a replaying
client would see them out of order. ``emit`` flushes first for exactly that
reason.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from agent.core.repo import Event, Repo

COALESCE_MS = 50.0
COALESCE_CHARS = 200

#: Event types that are buffered rather than written one per token.
DELTA_TYPES = frozenset({"text_delta", "thinking_delta"})


@dataclass(frozen=True)
class Envelope:
    """The wire shape of an event (section 8): run_id, seq, ts, type, data, agent."""

    run_id: str
    seq: int
    ts: int
    type: str
    data: Any
    agent: str = "main"

    def to_sse(self) -> dict[str, str]:
        """Frame for sse-starlette. ``id`` is the seq, which is what section 8
        means by "SSE id = seq" and what lets a client resume with ``?after=``."""
        import json

        body = json.dumps(
            {
                "run_id": self.run_id,
                "seq": self.seq,
                "ts": self.ts,
                "type": self.type,
                "data": self.data,
                "agent": self.agent,
            },
            ensure_ascii=False,
        )
        return {"id": str(self.seq), "data": body}


class Broadcaster:
    """Fan-out of envelopes to attached SSE subscribers."""

    def __init__(self, maxsize: int = 2000) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subs.discard(queue)

    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, envelope: Envelope) -> None:
        """Non-blocking. A subscriber that cannot keep up loses events and is
        expected to re-read from the database via ``?after=seq``."""
        for queue in list(self._subs):
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                self._subs.discard(queue)


@dataclass
class _Pending:
    """Buffered deltas for one event type, kept in arrival order."""

    text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    last_at: float = 0.0

    def add(self, piece: str, extra: dict[str, Any] | None = None) -> None:
        self.text += piece
        if extra:
            self.extra.update(extra)
        self.last_at = time.monotonic()


class EventSink:
    """Writes events for exactly one run."""

    def __init__(
        self,
        repo: Repo,
        broadcaster: Broadcaster,
        run_id: str,
        *,
        agent: str = "main",
        coalesce_ms: float = COALESCE_MS,
        coalesce_chars: int = COALESCE_CHARS,
    ) -> None:
        self.repo = repo
        self.broadcaster = broadcaster
        self.run_id = run_id
        self.agent = agent
        self._coalesce_ms = coalesce_ms
        self._coalesce_chars = coalesce_chars
        self._pending: dict[str, _Pending] = {}

    # ------------------------------------------------------------- writing --

    def emit(self, type: str, data: Any = None) -> Event:
        """Write one event immediately, after flushing anything buffered."""
        self.flush()
        return self._write(type, data)

    def buffer(self, type: str, text: str, **extra: Any) -> None:
        """Buffer a delta. Written on the next flush, or immediately if large."""
        if type not in DELTA_TYPES:
            self.emit(type, {"text": text, **extra} if extra else {"text": text})
            return
        pending = self._pending.setdefault(type, _Pending())
        pending.add(text, extra)
        if len(pending.text) >= self._coalesce_chars:
            self.flush()

    def flush(self) -> None:
        """Write every buffered delta, oldest type first, in arrival order."""
        if not self._pending:
            return
        for type, pending in list(self._pending.items()):
            if not pending.text:
                continue
            payload: dict[str, Any] = {"text": pending.text}
            payload.update(pending.extra)
            self._write(type, payload)
        self._pending.clear()

    def due(self) -> bool:
        """True when the coalescing window has elapsed."""
        if not self._pending:
            return False
        newest = max(p.last_at for p in self._pending.values())
        return (time.monotonic() - newest) * 1000.0 >= self._coalesce_ms

    def publish(self, event: Event) -> None:
        """Broadcast an event that was written by someone else.

        ``Repo.finalize_run`` writes the terminal event inside its own
        transaction, which is deliberate -- it must be atomic with the status
        change. That means it never passes through ``_write``, so nothing
        broadcasts it. Without this, a client learns the run finished only at
        the next SSE keep-alive, which looks like a multi-second hang after the
        answer is already on screen.
        """
        self.broadcaster.publish(
            Envelope(
                run_id=event.run_id, seq=event.seq, ts=event.ts,
                type=event.type, data=event.payload, agent=self.agent,
            )
        )

    def _write(self, type: str, data: Any) -> Event:
        event = self.repo.append_event(self.run_id, type, data)
        self.broadcaster.publish(
            Envelope(
                run_id=event.run_id, seq=event.seq, ts=event.ts,
                type=event.type, data=event.payload, agent=self.agent,
            )
        )
        return event


__all__ = [
    "COALESCE_CHARS",
    "COALESCE_MS",
    "DELTA_TYPES",
    "Broadcaster",
    "Envelope",
    "EventSink",
]
