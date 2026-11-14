"""One schema-constrained question to the model, asked by code (plan 3.1).

The workflow lane: code loops over the units of a task (one invoice, one
section, one changed block, one form), asks the model one question about each
with the answer's shape fixed by a JSON schema, then checks and assembles the
answers itself. Fill, Key moments and the pipeline tools all ask this way.

Every call goes through the same gates as the agent's own:

- the run's limits: it counts as a model call against `max_model_calls`, and
  none starts past `max_minutes` (agent/safety/limits.py);
- Stop: checked before each call, so a loop of twelve ends at the next one;
- the trace: the exact request and response, as `model_request` and
  `model_response`, through the run's observer (server/runs.py).

What comes back is data for code to check, never an action: no tools are
offered, and the answer is parsed against the schema.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from agent.config.settings import Settings
from agent.model import server as llama


class ModelCallError(ValueError):
    """The question could not be answered; the message is for the user."""


class Stopped(ModelCallError):
    """Stop was pressed, or the run's limits are spent."""


class ModelCall:
    def __init__(self, settings: Settings, *, observer: Callable[[dict[str, Any]], None] | None = None,
                 limits: Any = None, cancelled: Callable[[], bool] | None = None, timeout: float = 180.0) -> None:
        self.settings = settings
        self._observer = observer
        #: The run's RunLimits, when asked inside a run: `charge()` says why no more calls may start.
        self._limits = limits
        self._cancelled = cancelled or (lambda: False)
        self._timeout = timeout

    def ask(self, prompt: str, schema: dict[str, Any], *, system: str = "", name: str = "answer",
            max_tokens: int = 800, temperature: float = 0.2, thinking: bool = False) -> Any:
        """The model's answer to `prompt`, parsed: JSON that fits `schema` (llama.cpp's grammar holds it to it)."""
        if self._cancelled():
            raise Stopped("stopped")
        if self._limits is not None and (why := self._limits.charge()):
            raise Stopped(why)
        body = {
            "model": self.settings.model.name,
            "messages": [*([{"role": "system", "content": system}] if system else []),
                         {"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": thinking},
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        }
        self._observe({"type": "call_start", "lane": "workflow"})
        self._observe({"type": "model_request", "body": body})
        start = time.perf_counter()
        try:
            response = httpx.post(f"http://127.0.0.1:{self.settings.ports.llama}/v1/chat/completions", json=body,
                                  headers=llama.auth_headers(), timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            text = message.get("content") or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            self._observe({"type": "model_error", "error": f"{type(exc).__name__}: {str(exc)[:2000]}"})
            raise ModelCallError(f"the model could not answer: {exc}") from exc
        self._observe({"type": "model_response", "text": text, "reasoning": message.get("reasoning_content") or "",
                       "tool_calls": [], "finish_reason": data["choices"][0].get("finish_reason"),
                       "timings": data.get("timings"), "usage": data.get("usage"),
                       "ms": int((time.perf_counter() - start) * 1000)})
        if isinstance(data.get("timings"), dict):
            self._observe({"type": "call_timings", **data["timings"]})
        try:
            return json.loads(text or "{}")
        except ValueError as exc:   # cut off at max_tokens: the JSON never closed
            raise ModelCallError("the model's answer was cut off") from exc

    def _observe(self, event: dict[str, Any]) -> None:
        if self._observer is not None:
            self._observer(event)


__all__ = ["ModelCall", "ModelCallError", "Stopped"]
