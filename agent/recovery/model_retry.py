"""Recovering from failures inside a run, with Strands hooks rather than prompt text.

A 2B model does not reliably follow "if a tool fails, retry". It read a blank
error, said "same error", and stopped -- the Strands loop ends whenever the
model stops calling tools. These hooks always run, so recovery does not depend
on the model remembering an instruction.

`LocalModelRetry` -- the *model call* failed. Subclasses Strands'
`ModelRetryStrategy`, so the SDK's own retry loop does the work. Changed for a
local server: a fixed delay instead of exponential backoff (there is no rate
limit to wait out), a wider set of retryable errors (llama-server restarting,
a dropped connection, a 5xx), and an *empty* response counts as a failure -- a
small model sometimes thinks and then emits nothing at all.

`ToolFailureRecovery` -- a *tool call* failed:

1. A tool that **raised** is re-run via `AfterToolCallEvent.retry`, up to
   `tool_crash_retries`. Crashes are usually transient: a subprocess that
   could not spawn, a file briefly locked.
2. A shell command with a non-zero exit code is marked as an error.
3. A failed result gets a short instruction appended: read the error, fix the
   arguments, attempt N of M. The model sees it right after the error text.
4. If the model then **stops** straight after a failure, `AfterInvocationEvent`
   resumes it once. Past the failure limit the instruction flips to "stop and
   explain", so this cannot loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx
from strands.event_loop._retry import ModelRetryStrategy
from strands.hooks.events import (
    AfterModelCallEvent,
)
from strands.types.exceptions import ModelThrottledException

from agent.config.settings import ResilienceSettings

logger = logging.getLogger(__name__)


#: Called with a small dict describing what was retried; the run turns it into
#: an event so the UI can drop the discarded partial answer.
Notify = Callable[[dict[str, Any]], None]


class EmptyResponse(Exception):
    """The model finished without text or a tool call."""


class LocalModelRetry(ModelRetryStrategy):
    """`ModelRetryStrategy` tuned for a model on localhost."""

    def __init__(self, settings: ResilienceSettings, notify: Notify | None = None) -> None:
        super().__init__(max_attempts=settings.model_attempts)
        self._delay = settings.model_retry_delay
        self._notify = notify

    def is_retryable(self, exception: Exception) -> bool:
        if isinstance(exception, (ModelThrottledException, EmptyResponse, httpx.TransportError)):
            return True
        if isinstance(exception, httpx.HTTPStatusError):
            return exception.response.status_code >= 500
        return False

    def _calculate_delay(self, attempt: int) -> float:  # type: ignore[override]
        return self._delay

    async def _handle_after_model_call(self, event: AfterModelCallEvent) -> None:
        already = event.retry
        response = event.stop_response
        if not already and response is not None and _is_empty(response.message):
            # Treated exactly like a retryable exception, through the same
            # attempt counter, so an empty answer cannot retry forever.
            self._current_attempt += 1
            if self._current_attempt < self._max_attempts:
                await asyncio.sleep(self._delay)
                event.retry = True
                self._report("empty response")
            return
        await super()._handle_after_model_call(event)
        if event.retry and not already:
            self._report(type(event.exception).__name__ if event.exception else "error")

    def _report(self, reason: str) -> None:
        logger.info("model call retried (%s), attempt %d of %d",
                    reason, self._current_attempt + 1, self._max_attempts)
        if self._notify is not None:
            self._notify({"type": "model_retry", "reason": reason,
                          "attempt": self._current_attempt + 1, "of": self._max_attempts})


def _is_empty(message: dict[str, Any] | None) -> bool:
    """No visible text and no tool call. Reasoning alone does not count."""
    for block in (message or {}).get("content") or []:
        if not isinstance(block, dict):
            continue
        if "toolUse" in block or str(block.get("text", "")).strip():
            return False
    return True


__all__ = ["EmptyResponse", "LocalModelRetry", "Notify"]
