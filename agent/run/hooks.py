"""``RunEvents``: Strands hooks -> Atlas events and step rows (spec section 9).

All hooks for a run live in one provider so ordering is local and the executor
stays readable.

Two decisions worth recording:

* **Steps are built from complete messages, never from reassembled deltas.**
  ``MessageAddedEvent`` fires with a finished message, which is exactly the
  structural truth section 9 asks for. This also answers S4: the hook *does*
  fire for tool-result messages, which arrive as a ``user`` message carrying a
  ``toolResult`` block.
* **The user's own message is not a step.** User text already lives in
  ``nodes.content``; only a user message that carries tool results becomes a
  step.
"""

from __future__ import annotations

from typing import Any

from strands.hooks import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    MessageAddedEvent,
)

from agent.core.repo import Repo
from agent.run.events import EventSink


class RunEvents(HookProvider):
    """Emits the structural events of one run and writes its step rows."""

    def __init__(self, sink: EventSink, repo: Repo, node_id: str) -> None:
        self.sink = sink
        self.repo = repo
        self.node_id = node_id
        self._step_idx = 0
        self.iteration = 0
        #: Accumulated across every model call in the run, for runs.usage.
        self.usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}

    # ----------------------------------------------------------- lifecycle --

    def register_hooks(self, registry: Any, **_: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._before_invocation)
        registry.add_callback(AfterModelCallEvent, self._after_model_call)
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)
        registry.add_callback(MessageAddedEvent, self._message_added)

    def _before_invocation(self, event: BeforeInvocationEvent) -> None:
        if len(event.messages) == 1:
            self.sink.emit(
                "context_built",
                {
                    "tokens_before": None,
                    "tokens_after": None,
                    "budget": None,
                    "pruned": {},
                    "attachments": [],
                    "note": "ContextBuilder v0: no token accounting yet (L6)",
                },
            )

    def _after_model_call(self, event: AfterModelCallEvent) -> None:
        """Usage and iteration count for one model call.

        Tokens are accumulated here rather than in the executor: this hook is
        the only place that sees the model's metadata, and a tool-using run
        makes several calls that all have to add up.
        """
        self.iteration += 1
        usage = None
        if event.stop_response is not None:
            message = getattr(event.stop_response, "message", None)
            if isinstance(message, dict):
                usage = (message.get("metadata") or {}).get("usage")

        if usage:
            for key in ("inputTokens", "outputTokens", "totalTokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    self.usage[key] = self.usage.get(key, 0) + value

            self.sink.emit(
                "usage",
                {
                    "prompt_tokens": usage.get("inputTokens"),
                    "completion_tokens": usage.get("outputTokens"),
                    "iteration": self.iteration,
                },
            )

    # ---------------------------------------------------------------- tools --

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        self.sink.emit(
            "tool_call_started",
            {
                "call_id": event.tool_use.get("toolUseId"),
                "name": event.tool_use.get("name"),
                "arguments": event.tool_use.get("input"),
            },
        )

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        """Report the outcome, including a tool that *returned* a failure.

        ``event.result`` is a plain dict, not an object with attributes --
        probing it with ``getattr(result, "status")`` silently yields ``""``
        and every tool error is reported as a success. A tool that returns
        ``{"status": "error", ...}`` sets no exception, so the dict is the only
        place the failure is recorded.
        """
        result = event.result if isinstance(event.result, dict) else {}
        is_error = result.get("status") == "error" or event.exception is not None
        text = _result_text(result)
        self.sink.emit(
            "tool_call_finished",
            {
                "call_id": event.tool_use.get("toolUseId"),
                "status": "error" if is_error else "ok",
                "is_error": is_error,
                "result_preview": _preview(text),
                "result_truncated": len(text) > PREVIEW_CHARS,
                "duration_ms": getattr(event, "duration", None),
                "error": str(event.exception) if event.exception else None,
            },
        )

    # ---------------------------------------------------------------- steps --

    def _message_added(self, event: MessageAddedEvent) -> None:
        """One complete message -> one step per content block."""
        message = event.message
        role = message.get("role")
        blocks = message.get("content") or []

        if role == "user" and not any("toolResult" in b for b in blocks):
            return  # the user's own turn; it lives in nodes.content

        for block in blocks:
            if not isinstance(block, dict):
                continue
            if "reasoningContent" in block:
                self._write_step("thinking", block["reasoningContent"], status="complete")
            elif "text" in block:
                self._write_step("text", {"text": block["text"]}, status="complete")
            elif "toolUse" in block:
                call = block["toolUse"]
                self._write_step(
                    "tool_call",
                    {"name": call.get("name"), "input": call.get("input")},
                    call_id=call.get("toolUseId"),
                )
            elif "toolResult" in block:
                result = block["toolResult"]
                self._write_step(
                    "tool_result",
                    _result_content(result),
                    call_id=result.get("toolUseId"),
                    is_error=result.get("status") == "error",
                )

    def _write_step(
        self,
        kind: str,
        content: Any,
        *,
        status: str = "complete",
        call_id: str | None = None,
        is_error: bool = False,
    ) -> None:
        """Persist the step and announce it.

        In-progress steps exist only as events (section 8 rule 5); the row
        appears here, when the message is complete.
        """
        step = self.repo.add_step(
            node_id=self.node_id,
            idx=self._step_idx,
            kind=kind,
            content=content,
            status=status,
            call_id=call_id,
            is_error=is_error,
        )
        self._step_idx += 1
        self.sink.emit(
            "step_finished",
            {
                "step_id": step.id,
                "kind": kind,
                "status": status,
                "tokens": 0,
            },
        )


#: How much of a tool result the UI shows inline. The model already got the
#: real thing; this is only for the transcript.
PREVIEW_CHARS = 600


def _result_text(result: dict[str, Any]) -> str:
    """The text a model would actually see, without the envelope around it."""
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            return str(first["text"])
    return "" if content is None else str(content)


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + " ..."


def _result_content(result: dict[str, Any]) -> Any:
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            return {"text": first["text"]}
    return {"text": "" if content is None else str(content)}


__all__ = ["RunEvents"]
