"""The `subagent` tool, built by Atlas: workers that run under the same policy.

The harness can wire `subagent` itself, but it rebuilds a child from a fixed
set of its own arguments, and three things Atlas sets on every agent are not
among them: `callback_handler=None` (the default prints every token, which
once failed a run on an emoji), the local model-retry strategy, and the
conversation manager. So Atlas builds the tool with the harness's own
`build_default_subagent` and a child factory that adds them.

What a worker shares with its parent, on purpose:
- `ToolPolicy`, so every tool call it makes is checked the same way, with the
  same approver and the grants of this turn;
- `RunLimits`, so the message's 40 model calls and 15 minutes cover the
  parent and all its workers together;
- the taint tracker, so a page a worker fetched taints the chat.

What a worker gets its own of: `ToolFailureRecovery` (it resets its failure
budget at every invocation, so sharing it let a worker wipe the parent's, and
two workers raced on it), and a model object without the run's observer (a
worker's retries and stats must not redraw the parent's answer in the UI).
No session: the harness never gives a delegate one, so nothing a worker does
is written into the chat's history. Delegation is one level deep.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strands_harness import BUILTIN_TOOL_NAMES, create_harness
from strands_harness import defaults as harness_defaults
from strands_harness.tools.subagent import build_default_subagent

from agent.config.settings import Settings
from agent.recovery.model_retry import LocalModelRetry
from agent.recovery.tool_recovery import ToolFailureRecovery

#: Workers cannot delegate further.
MAX_DEPTH = 1


def worker_tool(settings: Settings, *, model: Any, builtin: list[str], builtin_extra: dict[str, Any],
                skills: Any, interventions: Any, tools: list[Any], hooks: list[Any], sandbox: Any,
                conversation_manager: Callable[[], Any]) -> Any:
    """The `subagent` tool for one turn. `model` is a model object without the
    run's observer; `hooks` are the parent's own instances."""
    builtin_tools = {name: (name in builtin and name != "subagent") for name in BUILTIN_TOOL_NAMES}
    builtin_tools.update({k: v for k, v in builtin_extra.items() if builtin_tools.get(k)})
    parent_config: dict[str, Any] = {
        "model": model, "effort": harness_defaults.DEFAULT_EFFORT, "caching": False, "context_manager": False,
        "builtin_tools": builtin_tools, "background_tasks": False, "builtin_plugins": [],
        "skills": skills, "memory": False, "session": False, "interventions": interventions,
        "plugins": [], "hooks": hooks, "tools": tools, "sandbox": sandbox,
    }

    def build_child(**config: Any) -> Any:
        own = [ToolFailureRecovery(settings.resilience) if isinstance(h, ToolFailureRecovery) else h
               for h in config.get("hooks") or []]
        return create_harness(**{**config, "hooks": own}, callback_handler=None,
                              retry_strategy=LocalModelRetry(settings.resilience),
                              conversation_manager=conversation_manager())

    return build_default_subagent(build_child, parent_config, memory=False, max_depth=MAX_DEPTH)


__all__ = ["MAX_DEPTH", "worker_tool"]
