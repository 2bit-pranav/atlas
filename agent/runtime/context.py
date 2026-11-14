"""Old tool results shortened to a one-line stub when a chat nears the window (plan 3.9).

Most of a long chat's context is tool results from earlier turns: a 16-page
PDF read, a workbook, a search. The answers built from them stay; the raw
results are rarely needed again, and the model can call the tool again if it
needs one. So when the history passes `prune_trigger_ratio` of the window, the
oldest earlier turns' results are replaced by a stub, oldest first, until it is
under `prune_target_ratio`. The current turn's results are never touched, and
nothing else is: no message is dropped, nothing is summarised by the model.

It changes the history only when the trigger is crossed, so llama.cpp's cached
prompt prefix survives every ordinary turn. The trimmed history is what the
next snapshot saves: the chat goes on from it. A context overflow trims every
earlier result at once; if that is not enough the error stands.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from strands.agent.conversation_manager import ConversationManager

logger = logging.getLogger(__name__)

#: Characters per token, rounded down for safety (Gemma's tokenizer gives ~4 for English).
CHARS_PER_TOKEN = 3.5
#: A result this short is left as it is: the stub would save nothing.
MIN_RESULT = 400


def _size(messages: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages, default=str, ensure_ascii=False))


def _current_start(messages: list[dict[str, Any]]) -> int:
    """Where the current turn begins: the last user message with text (not a tool result)."""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "user" and any("text" in b for b in m.get("content") or []):
            return i
    return len(messages)


def _stub(result: dict[str, Any], name: str) -> dict[str, Any]:
    size = sum(len(str(b.get("text", ""))) for b in result.get("content") or [] if isinstance(b, dict))
    return {**result, "content": [{"text": f"[Earlier result of {name}, {size:,} characters, removed to save "
                                           "space. Call the tool again if you need it.]"}]}


def trim(messages: list[dict[str, Any]], limit_chars: int) -> int:
    """Stub earlier turns' tool results, oldest first, until the history is under `limit_chars`.
    Changes `messages` in place; returns how many results were stubbed."""
    end = _current_start(messages)
    names: dict[str, str] = {}
    done = 0
    for i in range(end):
        if _size(messages) <= limit_chars:
            break
        content = messages[i].get("content") or []
        for k, block in enumerate(content):
            if "toolUse" in block:
                names[block["toolUse"].get("toolUseId", "")] = block["toolUse"].get("name", "a tool")
            result = block.get("toolResult")
            if not result or (result.get("content") and str(result["content"][0].get("text", "")).startswith("[Earlier result")):
                continue
            if sum(len(str(b.get("text", ""))) for b in result.get("content") or [] if isinstance(b, dict)) < MIN_RESULT:
                continue
            content[k] = {**block, "toolResult": _stub(result, names.get(result.get("toolUseId", ""), "a tool"))}
            done += 1
    return done


class TrimToolResults(ConversationManager):
    def __init__(self, window_tokens: int, trigger: float, target: float) -> None:
        super().__init__()
        self.trigger_chars = int(window_tokens * trigger * CHARS_PER_TOKEN)
        self.target_chars = int(window_tokens * target * CHARS_PER_TOKEN)

    def apply_management(self, agent: Any, **kwargs: Any) -> None:
        if _size(agent.messages) > self.trigger_chars:
            n = trim(agent.messages, self.target_chars)
            logger.info("context near the window: %d earlier tool results shortened", n)

    def reduce_context(self, agent: Any, e: Exception | None = None, **kwargs: Any) -> None:
        if not trim(agent.messages, 0 if e is not None else self.target_chars) and e is not None:
            raise e


__all__ = ["TrimToolResults", "trim"]
