"""The plan: write it first, keep it true, finish it.

The harness's `todos` plugin gives the model `todo_write` (it rewrites the
whole list, so it can check items off, reorder, reword, add and drop them)
and shows the list again before every model call, so the model works against
it. Two things are Atlas's:

- **Finishing.** A small model announces it is done with steps still open
  (bench_multi, 2026-11-04: "the report has been written" with no report).
  When it ends its turn with open items, it is sent back once with them
  listed: finish them, or update the plan if they no longer apply.
- **A plan per message.** The list lives in the agent's state, which the
  snapshot saves; a finished plan is cleared when the next message starts, so
  it is not re-shown, at a cost in tokens, for the rest of the chat. An
  unfinished one stays ("continue" picks it up).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent, BeforeInvocationEvent

logger = logging.getLogger(__name__)

#: Where the harness's todos plugin keeps the list.
STATE_KEY = "todos"

#: Told to the model, in the system prompt, when the plan tool is on.
GUIDANCE = (
    "For a task with several parts, first call todo_write with one item per step. Work through it, "
    "and after each step call todo_write again: mark the step completed, and when what you found "
    "changes the plan, add, remove, reorder or reword the remaining steps. Do not give your final "
    "answer while a step is still pending: finish it, or remove it from the plan if it no longer applies."
)


def open_items(agent: Any) -> list[str]:
    todos = agent.state.get(STATE_KEY) or []
    return [str(t.get("content", "")) for t in todos if isinstance(t, dict) and t.get("status") != "completed"]


class PlanCheck(HookProvider):
    """Sends the model back once when it ends its turn with plan items open."""

    def __init__(self, notify: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._notify = notify
        self._resumed = False

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._before)
        registry.add_callback(AfterInvocationEvent, self._after)

    def _before(self, event: BeforeInvocationEvent) -> None:
        if self._resumed:
            return  # our own resume: same message, same plan
        todos = event.agent.state.get(STATE_KEY)
        if todos and not open_items(event.agent):
            event.agent.state.delete(STATE_KEY)  # last message's finished plan

    def _after(self, event: AfterInvocationEvent) -> None:
        if self._resumed or event.resume is not None:
            return
        result = event.result
        if result is None or getattr(result, "stop_reason", None) != "end_turn":
            return  # stopped by a limit, cancelled, or failed: not "done too early"
        left = open_items(event.agent)
        if not left:
            return
        self._resumed = True
        logger.info("turn ended with %d plan items open; resuming once", len(left))
        if self._notify is not None:
            self._notify({"type": "resumed", "reason": "plan not finished"})
        event.resume = ("[Atlas] Your plan still has steps that are not completed:\n"
                        + "\n".join(f"- {item}" for item in left)
                        + "\nDo them now, or call todo_write to remove the ones that no longer apply, "
                          "then give your final answer.")


__all__ = ["GUIDANCE", "PlanCheck", "open_items"]
