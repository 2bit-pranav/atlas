"""A scripted model for tests and evals (spec section 19, ground rules).

Runs that need no real model must be deterministic and GPU-free, so the whole
test suite drives this instead of llama-server. It is also useful interactively
for exercising the API without burning tokens.

Set ``ATLAS_FAKE_MODEL=1`` and the backend builds this instead of
``AtlasLlamaCppModel``. Script it by passing explicit turns::

    FakeModel(["Hello", "Second answer"])
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeTurn:
    """One scripted response."""

    text: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None


class FakeModel:
    """Minimal Model implementation that replays scripted turns."""

    DEFAULT_TURNS = ["Hello. I am Atlas."]

    def __init__(
        self,
        turns: list[FakeTurn | str] | None = None,
        *,
        delay: float = 0.0,
    ) -> None:
        self.turns: list[FakeTurn] = [
            FakeTurn(text=t) if isinstance(t, str) else t
            for t in (turns if turns is not None else self.DEFAULT_TURNS)
        ]
        self.delay = delay
        self._index = 0
        self.calls: list[list[dict[str, Any]]] = []
        self.config: dict[str, Any] = {}
        #: Set to make the next stream raise, for failure-path tests.
        self.fail_with: Exception | None = None
        #: Strands' Agent checks this; Atlas is stateless per run (section 9).
        self.stateful = False

    # ------------------------------------------------------------- driving --

    def _next(self) -> FakeTurn:
        if self._index < len(self.turns):
            turn = self.turns[self._index]
            self._index += 1
            return turn
        return FakeTurn(text="(fake model: out of scripted turns)")

    @property
    def remaining(self) -> int:
        return max(0, len(self.turns) - self._index)

    # ------------------------------------------------------- Model surface --

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls.append(list(messages))
        if self.fail_with is not None:
            raise self.fail_with

        turn = self._next()

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}

        if turn.thinking:
            yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": turn.thinking}}}}
            yield {"contentBlockStop": {}}
            yield {"contentBlockStart": {"start": {}}}

        words = turn.text.split(" ") or [""]
        per_word = self.delay / max(1, len(words))
        for word in words:
            if per_word:
                # Paced so tests can observe a run in flight (409 on a second
                # start) and cancel mid-stream.
                await asyncio.sleep(per_word)
            yield {"contentBlockDelta": {"delta": {"text": word + " "}}}
        yield {"contentBlockStop": {}}

        stop = "tool_use" if turn.tool_calls else "end_turn"
        for index, call in enumerate(turn.tool_calls):
            yield {"contentBlockStart": {"start": {"toolUse": {
                "name": call["name"], "toolUseId": call.get("id", f"call_{index}")}}}}
            import json as _json
            yield {"contentBlockDelta": {"delta": {"toolUse": {
                "input": _json.dumps(call.get("input", {}))}}}}
            yield {"contentBlockStop": {}}

        yield {"messageStop": {"stopReason": stop}}
        yield {"metadata": {
            "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
            "metrics": {"latencyMs": 1},
        }}

    async def structured_output(self, *args, **kwargs):
        raise NotImplementedError("FakeModel does not do structured output")

    async def count_tokens(self, *args, **kwargs) -> int:
        return 0

    def update_config(self, **kwargs) -> None:
        self.config.update(kwargs)

    def get_config(self) -> dict[str, Any]:
        return dict(self.config)

    def set_thinking(self, enabled: bool) -> None:
        """The adapter exposes this; keep the same surface so callers can."""
        self.config["enable_thinking"] = enabled

    @property
    def context_window_limit(self) -> int:
        return 32768


__all__ = ["FakeModel", "FakeTurn"]
