"""Fold a run's events into what the UI shows for the turn.

The same fold runs in two places: here, so a finished turn can be stored as
`render_json` and reopened without replaying a snapshot, and in the client's
store, so the live view and the reloaded view are built by the same rules. If
one changes, change the other (`client/src/lib/transcript.ts`).

Parts:

    {"kind": "reasoning", "text": ...}
    {"kind": "text", "text": ...}
    {"kind": "tool", "id", "name", "args", "status", "text"}

Consecutive deltas of one kind merge into one part, otherwise a 400-token
answer would be 400 parts.

A model call that is retried (resilience.LocalModelRetry) has already streamed
some of its output. `call_start` marks where each call began, and
`model_retry` cuts the parts back to that mark, so the discarded attempt does
not stay on screen above the real one.
"""

from __future__ import annotations

import time
from typing import Any


class Transcript:
    def __init__(self, context_size: int) -> None:
        self.parts: list[dict[str, Any]] = []
        self._call_mark = 0
        self._started = time.time()
        self.stats: dict[str, Any] = {"context_size": context_size, "model_calls": 0}

    # ------------------------------------------------------------- folding --

    def fold(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "call_start":
            self._call_mark = len(self.parts)
            self.stats["model_calls"] += 1
        elif kind == "model_retry":
            del self.parts[self._call_mark:]
        elif kind == "thinking_delta":
            self._append("reasoning", event.get("text", ""))
        elif kind == "text_delta":
            self._append("text", event.get("text", ""))
        elif kind == "tool_start":
            self.parts.append({"kind": "tool", "id": event.get("id"), "name": event.get("name"),
                               "args": event.get("args") or {}, "status": "running", "text": ""})
        elif kind == "tool_args_delta":
            for part in self._tools(event.get("id")):
                part["args"] = event.get("args")
        elif kind == "tool_end":
            for part in self._tools(event.get("id")):
                part["status"] = "error" if event.get("status") == "error" else "success"
                part["text"] = event.get("text", "")
        elif kind == "stats":
            self.stats.update({k: v for k, v in event.items() if k not in ("type", "seq")})

    def _append(self, kind: str, text: str) -> None:
        if not text:
            return
        last = self.parts[-1] if self.parts else None
        if last is not None and last["kind"] == kind:
            last["text"] += text
        else:
            self.parts.append({"kind": kind, "text": text})

    def _tools(self, tool_id: Any) -> list[dict[str, Any]]:
        return [p for p in self.parts if p["kind"] == "tool" and p["id"] == tool_id]

    # -------------------------------------------------------------- output --

    def final_stats(self) -> dict[str, Any]:
        return {**self.stats, "duration_ms": int((time.time() - self._started) * 1000)}

    def answer_text(self) -> str:
        """The visible answer, for quoting in a retry hint."""
        return "".join(p["text"] for p in self.parts if p["kind"] == "text")


def stats_from_timings(timings: dict[str, Any]) -> dict[str, Any]:
    """llama-server `timings` -> the fields the context meter shows.

    The context in use is everything in the slot: the cached prefix, the newly
    read prompt, and what has been generated so far.
    """
    cached = int(timings.get("cache_n") or 0)
    prompt = int(timings.get("prompt_n") or 0)
    predicted = int(timings.get("predicted_n") or 0)
    return {
        "context_used": cached + prompt + predicted,
        "prompt_tokens": cached + prompt,
        "completion_tokens": predicted,
        "tokens_per_second": round(float(timings.get("predicted_per_second") or 0), 1),
        "prompt_per_second": round(float(timings.get("prompt_per_second") or 0), 1),
    }


def answer_of(render: list[dict[str, Any]] | None) -> str:
    return "".join(p.get("text", "") for p in (render or []) if p.get("kind") == "text")


__all__ = ["Transcript", "answer_of", "stats_from_timings"]
