"""`ToolManager` (agent/AGENTS.md).

Turns `tools.builtin` into the harness's `builtin_tools` list. It resolves
configuration and nothing else: no tool logic, no filtering of what the model
may call, no intervention handling. The harness owns tool behaviour.

It exists so `sampling` and `tools` stay separate concerns, and so dropping
`shell` is a settings edit rather than a code change.
"""

from __future__ import annotations

from typing import Any

from strands_harness import BUILTIN_TOOL_NAMES

from agent.core.settings import Settings

#: The built-in tools a user can switch on, in `tools.builtin`. Every name here
#: must exist in `BUILTIN_TOOL_NAMES`; a typo would otherwise be a tool that
#: silently never appears.
SWITCHABLE: tuple[str, ...] = ("read", "write", "edit", "shell", "web_fetch", "subagent")

#: Deliberately never offered. `web_search` needs a cloud provider's native
#: search or Exa, a third party that would see every query.
#: `programmatic_tool_caller` lets the model run tools without asking.
BLOCKED: frozenset[str] = frozenset({"web_search", "programmatic_tool_caller"})


class ToolManager:
    """Resolves `tools.builtin` into harness built-in tool names."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def builtin_tools(self) -> list[str]:
        """The built-in tools to request, in the harness's own order.

        Stable because the tool list is part of the prompt prefix: reordering it
        between turns would change the cached prefix and cost a full re-read.
        """
        switches = self.settings.tools.builtin.model_dump()
        selected = {name for name in SWITCHABLE if switches.get(name)}
        unknown = selected - set(BUILTIN_TOOL_NAMES)
        if unknown:
            raise ValueError(
                f"unknown built-in tool names {sorted(unknown)}. "
                f"The harness provides: {sorted(BUILTIN_TOOL_NAMES)}"
            )
        return [n for n in BUILTIN_TOOL_NAMES if n in selected]

    def interventions(self) -> Any:
        """The `interventions=` argument, or None when approval is off.

        Off for now: there is no frontend to render an approval prompt, so
        enabling it would hang a run with nothing to answer it.
        """
        return None if not self.settings.tools.interventions else []

    def extra_tools(self) -> list[Any]:
        """Consumer-supplied tools. None yet: skills are scripts run via shell."""
        return []

    def describe(self) -> dict[str, Any]:
        """For `GET /settings`: what the switches actually resolved to."""
        return {
            "available": list(SWITCHABLE),
            "builtin_tools": self.builtin_tools(),
            "interventions": self.settings.tools.interventions,
        }


__all__ = ["BLOCKED", "SWITCHABLE", "ToolManager"]