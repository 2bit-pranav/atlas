"""Cheap limits on every run: model calls, wall clock, the same call repeated.

A 2B model can loop: the same `ls` again and again, or model calls that never
reach an answer. Until now only the user's Stop ended that, and a run with
nobody watching would never end. One hook per run (a new agent every turn, so
the counts start at zero with each message, and a resume keeps them):

- past `max_model_calls` or `max_minutes`, the next model call is cancelled
  with a message, which Strands makes the turn's answer: the run ends cleanly,
  and "continue" goes on from there (the work so far is in the history);
- past `max_minutes`, a tool call is refused too, so no new work starts;
- the same tool with the same arguments past `repeat_limit` is refused, and
  the model is told to use the result it already has.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from strands.hooks import BeforeModelCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from agent.config.settings import LimitsSettings


class RunLimits(HookProvider):
    def __init__(self, settings: LimitsSettings, notify: Callable[[dict[str, Any]], None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self._notify = notify or (lambda _event: None)
        self._clock = clock
        self._started: float | None = None
        self._model_calls = 0
        self._calls: Counter[str] = Counter()
        self._stopped: str | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self.before_model_call)
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)

    # ------------------------------------------------------------- hooks --

    def before_model_call(self, event: Any) -> None:
        self._start()
        self._model_calls += 1
        reason = self._past_time() or (
            f"{self.settings.max_model_calls} model calls" if self._model_calls > self.settings.max_model_calls else None)
        if reason:
            event.cancel = self._stop(reason)

    def before_tool_call(self, event: Any) -> None:
        self._start()
        if reason := self._past_time():
            event.cancel_tool = self._stop(reason)
            return
        use = event.tool_use
        key = f"{use.get('name')}:{json.dumps(use.get('input'), sort_keys=True, default=str)}"
        self._calls[key] += 1
        if self._calls[key] > self.settings.repeat_limit:
            event.cancel_tool = (f"Refused: this exact call has already run {self.settings.repeat_limit} "
                                 "time(s) in this message. Use the result you already have, or try "
                                 "something different; repeating it will not change the answer.")

    # ----------------------------------------------------------- helpers --

    def _start(self) -> None:
        if self._started is None:
            self._started = self._clock()

    def _past_time(self) -> str | None:
        assert self._started is not None
        if self._clock() - self._started > self.settings.max_minutes * 60:
            return f"{self.settings.max_minutes} minutes"
        return None

    def _stop(self, reason: str) -> str:
        message = (f"Stopped: this message reached its limit of {reason}. The work so far is above; "
                   "reply \"continue\" to go on from here, or raise the limit in Settings > "
                   "Recovery & context > Limits.")
        if self._stopped is None:
            self._stopped = message
            self._notify({"type": "limit", "text": message})
        return message


__all__ = ["RunLimits"]
