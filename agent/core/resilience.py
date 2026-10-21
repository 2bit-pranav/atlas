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
import json
import logging
from collections import Counter
from typing import Any, Callable

import httpx
from strands.event_loop._retry import ModelRetryStrategy
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
)
from strands.types.exceptions import ModelThrottledException

from agent.core.settings import ResilienceSettings

logger = logging.getLogger(__name__)

#: Called with a small dict describing what was retried; the run turns it into
#: an event so the UI can drop the discarded partial answer.
Notify = Callable[[dict[str, Any]], None]

NUDGE = (
    "Your last tool call failed and you stopped. Read the error above, then "
    "fix the command or arguments, or try a different way, and continue. If it "
    "really cannot be done, tell the user exactly what failed and why."
)


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


class ToolFailureRecovery(HookProvider):
    """Keeps a run going after a tool fails, within a fixed budget per turn."""

    def __init__(self, settings: ResilienceSettings, notify: Notify | None = None) -> None:
        self.settings = settings
        self._notify = notify
        self._crashes: Counter[str] = Counter()
        self._failures = 0
        self._last_failed = False
        self._nudged = False
        self._resuming = False

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._before_invocation)
        registry.add_callback(AfterToolCallEvent, self._after_tool)
        registry.add_callback(AfterInvocationEvent, self._after_invocation)

    def _before_invocation(self, event: BeforeInvocationEvent) -> None:
        # A resume is a new invocation of the same turn: keep the budget.
        if self._resuming:
            self._resuming = False
            return
        self._crashes.clear()
        self._failures = 0
        self._last_failed = False
        self._nudged = False

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        use_id = str(event.tool_use.get("toolUseId", ""))
        if event.exception is not None and event.cancel_message is None:
            if self._crashes[use_id] < self.settings.tool_crash_retries:
                self._crashes[use_id] += 1
                logger.info("tool %s raised %s; re-running", event.tool_use.get("name"),
                            type(event.exception).__name__)
                event.retry = True
                return

        if _nonzero_exit(event.result):
            # The harness's `shell` reports a command that exited non-zero as
            # a *successful* tool call. The model then reads "success" and
            # tells the user it worked; mark it as the failure it is.
            event.result = {**event.result, "status": "error"}

        if event.result.get("status") != "error" or event.cancel_message is not None:
            self._last_failed = False
            return

        self._failures += 1
        self._last_failed = True
        limit = self.settings.tool_failure_limit
        if self._failures < limit:
            note = (f"[Atlas] This call failed ({self._failures} of {limit} allowed failures "
                    "this turn). Read the error above, fix the arguments or try a "
                    "different command, and call a tool again. Do not guess why it failed.")
        else:
            note = (f"[Atlas] {limit} tool calls have failed this turn. Stop calling tools. "
                    "Tell the user what you tried, the exact error, and what they could do.")
        content = list(event.result.get("content") or [])
        if not any(isinstance(b, dict) and str(b.get("text", "")).strip() for b in content):
            # A blank error is the worst case for a small model: say so plainly.
            content.append({"text": "The tool failed without an error message."})
        content.append({"text": note})
        event.result = {**event.result, "content": content}

    def _after_invocation(self, event: AfterInvocationEvent) -> None:
        if not (self.settings.nudge_after_failure and self._last_failed and not self._nudged):
            return
        if self._failures >= self.settings.tool_failure_limit:
            return
        result = event.result
        if result is None or getattr(result, "stop_reason", None) != "end_turn":
            return
        self._nudged = True
        self._resuming = True
        logger.info("model stopped after a failed tool call; resuming once")
        if self._notify is not None:
            # The answer it gave up with is now out of date; the UI folds it away.
            self._notify({"type": "resumed", "reason": "tool failure"})
        event.resume = NUDGE


def _nonzero_exit(result: dict[str, Any]) -> bool:
    """True for a shell result whose JSON body carries a non-zero `exit_code`."""
    for block in result.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if not isinstance(text, str) or '"exit_code"' not in text:
            continue
        try:
            code = json.loads(text).get("exit_code")
        except (ValueError, AttributeError):
            continue
        if isinstance(code, int) and code != 0:
            return True
    return False


def _is_empty(message: dict[str, Any] | None) -> bool:
    """No visible text and no tool call. Reasoning alone does not count."""
    for block in (message or {}).get("content") or []:
        if not isinstance(block, dict):
            continue
        if "toolUse" in block or str(block.get("text", "")).strip():
            return False
    return True


__all__ = ["EmptyResponse", "LocalModelRetry", "NUDGE", "ToolFailureRecovery"]
