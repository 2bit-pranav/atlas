"""`ToolManager` (design.md 1a).

Turns `tools.groups` into the harness's `builtin_tools` list. It resolves
configuration and nothing else: no tool logic, no filtering of what the model
may call, no intervention handling. The harness owns tool behaviour.

The `groups` -> names mapping is the whole point of the manager. It exists so
`sampling` and `tools` stay separate concerns, and so dropping `shell` is a
settings edit rather than a code change.
"""

from __future__ import annotations

from typing import Any

from strands_harness import BUILTIN_TOOL_NAMES

from agent.core.settings import Settings

#: Group -> the built-in tool names it turns on. Every name here must exist in
#: `BUILTIN_TOOL_NAMES`; `test_tool_manager.py` asserts that, because a typo
#: would otherwise be a tool that silently never appears.
GROUPS: dict[str, tuple[str, ...]] = {
    "files": ("read", "write", "edit"),
    "shell": ("shell",),
    "web": ("web_fetch",),
    "subagents": ("subagent",),
}

#: Deliberately absent from every group. `web_search` needs a cloud provider's
#: native search or Exa, a third party that would see every query (design.md
#: L8). `programmatic_tool_caller` lets the model run tools without asking.
BLOCKED: frozenset[str] = frozenset({"web_search", "programmatic_tool_caller"})


class ToolManager:
    """Resolves `tools.groups` into harness built-in tool names."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def builtin_tools(self) -> list[str]:
        """The built-in tools to request, in a stable order.

        Stable because the tool list is part of the prompt prefix: reordering it
        between turns would change the cached prefix and cost a full re-read.
        """
        groups = self.settings.tools.groups
        selected: set[str] = set()
        for name, enabled in (
            ("files", groups.files),
            ("shell", groups.shell),
            ("web", groups.web),
            ("subagents", groups.subagents),
        ):
            if enabled:
                selected.update(GROUPS[name])

        blocked = selected & BLOCKED
        if blocked:
            raise ValueError(
                f"tools.groups selected blocked tools: {sorted(blocked)}. "
                "These are never available; remove them from the group mapping."
            )
        unknown = selected - set(BUILTIN_TOOL_NAMES)
        if unknown:
            raise ValueError(
                f"unknown built-in tool names {sorted(unknown)}. "
                f"The harness provides: {sorted(BUILTIN_TOOL_NAMES)}"
            )
        # Order by the harness's own declaration, not by group order.
        return [n for n in BUILTIN_TOOL_NAMES if n in selected]

    def interventions(self) -> Any:
        """The `interventions=` argument, or None when approval is off.

        Off for now: there is no frontend to render an approval prompt, so
        enabling it would hang a run with nothing to answer it (design.md L5).
        """
        return None if not self.settings.tools.interventions else []

    def extra_tools(self) -> list[Any]:
        """Consumer-supplied tools. None yet: skills are scripts run via shell."""
        return []

    def describe(self) -> dict[str, Any]:
        """For `GET /settings`: what the groups actually resolved to."""
        return {
            "groups": self.settings.tools.groups.model_dump(),
            "builtin_tools": self.builtin_tools(),
            "interventions": self.settings.tools.interventions,
        }


__all__ = ["BLOCKED", "GROUPS", "ToolManager"]