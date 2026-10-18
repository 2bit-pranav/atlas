"""Turn Strands' built-in event stream into flat API events.

**No custom hook providers.** Decision 2026-10-17, after measuring what
`stream_async` already reports: text and reasoning as `data`/`delta`, tool
arguments incrementally as `type: tool_use_stream`, and a tool result as a
`message` event carrying `toolResult`. Registering hooks as well would mean two
sources for the same fact and two places to keep in sync.

So this module is a *parser*, not an observer. It knows Strands' event shapes,
which is exactly the knowledge we were trying to keep in one file.

Two things worth knowing about the shapes, both learned the hard way:

* Raw model events are nested under an `event` key
  (`{"event": {"contentBlockStart": {...}}, ...}`), not top-level. Reading
  `ev["contentBlockStart"]` finds nothing.
* There is no flat "tool finished" event. A result shows up as a complete
  `toolResult` message, which means the tool's arguments have to be remembered
  from when they streamed in, so a `toolUseId -> name` map is kept. That map is
  the whole reason this file exists.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator

#: What the API layer streams to a browser.
#
#   text_delta        visible answer text
#   thinking_delta    reasoning, kept separate (S13: never replayed)
#   tool_start        a tool is about to run, with its arguments
#   tool_args_delta   arguments still arriving (a long command types itself out)
#   tool_end          the tool finished, with status and duration if known
#   usage             token counts, when the model reports them
#   done              the run finished; always the last event
#   error             something failed; always the last event


async def translate(
    events: AsyncIterator[dict[str, Any]] | Iterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Convert a Strands event stream into API events.

    An async generator, and one instance must span the whole run: the
    toolUseId -> name map below is state that a per-event call would discard.

    Yields nothing for anything it does not recognise, so an unrecognised
    Strands event is invisible rather than fatal.
    """
    # toolUseId -> name, so a bare toolResult can be attributed to a tool.
    pending: dict[str, str] = {}
    args: dict[str, dict[str, Any]] = {}

    async for ev in events:
        if not isinstance(ev, dict):
            continue

        # --- raw model events, nested under "event" -------------------
        # Reasoning appears ONLY here. There is no normalized event for it, so
        # a layer that reads top-level keys silently drops every thinking
        # delta and the UI shows an answer with no reasoning above it.
        inner = ev.get("event")
        if isinstance(inner, dict):
            produced = _from_raw(inner)
            if produced is not None:
                yield produced
                continue
            # Usage arrives on the raw `metadata` event, once per model call.
            for key in ("metadata", "messageStop"):
                block = inner.get(key)
                if isinstance(block, dict) and isinstance(block.get("usage"), dict):
                    yield _event("usage", **_usage(block["usage"]))
                    break
            continue

        # Strands ALSO reports every reasoning token as a normalized
        # `{"reasoningText": ..., "delta": {"reasoningContent": ...}}` event.
        # Translating that one as well sent each token twice, which the UI
        # showed as "TheThe user user is is". The raw event above is the one
        # source; the normalized duplicate is skipped here on purpose.
        delta = ev.get("delta")
        if ev.get("reasoning") or (isinstance(delta, dict) and "reasoningContent" in delta):
            continue

        # --- text ------------------------------------------------------
        data = ev.get("data")
        if isinstance(data, str) and data:
            yield _event("text_delta", text=data)
            continue

        # --- tool arguments, still arriving ---------------------------
        if ev.get("type") == "tool_use_stream":
            use = (delta or {}).get("toolUse") or {}
            raw = use.get("input")
            tid = _tool_use_id(delta) or "?"
            name = (ev.get("current_tool_use") or {}).get("name")
            if name and tid not in pending:
                pending[tid] = str(name)
            if isinstance(raw, str) and raw:
                parsed = _maybe_json(raw)
                if parsed is not None:
                    args[tid] = parsed
                    yield _event("tool_args_delta", id=tid,
                                 name=pending.get(tid), args=parsed)
            continue

        # --- complete messages ----------------------------------------
        message = ev.get("message")
        if isinstance(message, dict):
            for produced in _from_message(message, pending, args):
                yield produced
            continue

        # The terminal `result` event is deliberately NOT translated. `Run.finish`
        # emits the single authoritative `done`, carrying the real status; a
        # second one here arrived with no status and made every client see two
        # "done" events, one of them meaningless.


def _from_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One nested model event, or None if it carries nothing we emit.

    Only reasoning is translated. Text, tool names and tool results all have
    normalized events, and duplicating them here would send every word twice.
    """
    delta = raw.get("contentBlockDelta")
    if isinstance(delta, dict):
        inner = delta.get("delta")
        if isinstance(inner, dict) and "reasoningContent" in inner:
            text = _reasoning_text(inner["reasoningContent"])
            if text:
                return _event("thinking_delta", text=text)
    return None


def _from_message(
    message: dict[str, Any],
    pending: dict[str, str],
    args: dict[str, dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """One complete message: a tool call, a tool result, or plain text."""
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue

        if "toolUse" in block:
            use = block["toolUse"] or {}
            tid = str(use.get("toolUseId", ""))
            name = str(use.get("name", ""))
            if tid:
                pending[tid] = name
            yield _event("tool_start", id=tid, name=name, args=use.get("input") or {})
            continue

        if "toolResult" in block:
            result = block["toolResult"] or {}
            tid = str(result.get("toolUseId", ""))
            status = str(result.get("status", "unknown"))
            yield _event(
                "tool_end",
                id=tid,
                name=pending.pop(tid, "?"),
                status=status,
                text=_result_text(result),
            )
            args.pop(tid, None)
            continue

        if "text" in block and block["text"]:
            # Complete-message text is a duplicate of what already streamed as
            # deltas. Emitting it would double every word.
            continue


def _reasoning_text(block: Any) -> str:
    if isinstance(block, dict):
        if isinstance(block.get("reasoningText"), dict):
            return str(block["reasoningText"].get("text", ""))
        return str(block.get("text", ""))
    return ""


def _result_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict)
        )
    return str(content or "")


def _tool_use_id(delta: Any) -> str | None:
    if isinstance(delta, dict):
        use = delta.get("toolUse")
        if isinstance(use, dict):
            tid = use.get("toolUseId")
            if tid:
                return str(tid)
    return None


def _usage(raw: dict[str, Any]) -> dict[str, int]:
    """Token counts, with an all-zero result reported as unknown.

    A stub model reports zero, and a real one that genuinely used nothing is
    indistinguishable. Claiming "0 tokens" when the truth is "not reported"
    would make a cost display quietly lie.
    """
    counts = {
        "input": int(raw.get("inputTokens", 0) or 0),
        "output": int(raw.get("outputTokens", 0) or 0),
        "total": int(raw.get("totalTokens", 0) or 0),
    }
    if not any(counts.values()):
        counts["reported"] = 0
    return counts


def _maybe_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _event(kind: str, **fields: Any) -> dict[str, Any]:
    return {"type": kind, **fields}


async def _aiter(source: Any) -> AsyncIterator[dict[str, Any]]:
    """Normalise a sync or async source into an async iterator."""
    if hasattr(source, "__aiter__"):
        async for item in source:
            yield item
    else:
        for item in source:
            yield item


__all__ = ["translate"]