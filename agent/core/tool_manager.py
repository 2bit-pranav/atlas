"""`ToolManager`: turns `tools.builtin` into the harness's `builtin_tools` list.

It resolves configuration and nothing else, so dropping `shell` is a settings
edit rather than a code change. Checks before a tool runs are `policy.py`'s.
"""

from __future__ import annotations

from typing import Any

from strands_harness import BUILTIN_TOOL_NAMES

from agent.core.settings import Settings

#: The built-in tools a user can switch on, in `tools.builtin`. Every name here
#: must exist in `BUILTIN_TOOL_NAMES`; a typo would otherwise be a tool that
#: silently never appears. Deliberately absent: `web_search` (needs a cloud
#: provider's search or Exa, a third party that would see every query) and
#: `programmatic_tool_caller` (lets the model run tools without asking).
SWITCHABLE: tuple[str, ...] = ("read", "write", "edit", "shell", "web_fetch", "subagent")


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
        """The `interventions=` argument, or None when `tools.interventions` is off.

        Off by default: the UI does not render the harness's own intervention
        prompts (approvals go through `ToolPolicy`), so enabling it would hang a
        run with nothing to answer it.
        """
        return None if not self.settings.tools.interventions else []

    def extra_tools(self) -> list[Any]:
        """Extra tools from settings. None: skills are scripts run via `shell`."""
        return []

    def describe(self) -> dict[str, Any]:
        """For `GET /settings`: what the switches actually resolved to."""
        return {
            "available": list(SWITCHABLE),
            "builtin_tools": self.builtin_tools(),
            "interventions": self.settings.tools.interventions,
        }


__all__ = ["SWITCHABLE", "ToolManager"]