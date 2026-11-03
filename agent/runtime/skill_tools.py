"""Writing tools arrive with their skill.

Reading is global; creating and editing a document are registered only once
the model loads a skill that writes (`SKILL_TOOLS`), so a chat that only reads
never carries their schemas. Strands takes the tool list from the registry
before every model call, so a tool registered after `skills` runs is offered
on the very next call.

The skills plugin records activated skills in the agent's state, which the
session snapshot saves, so a later turn is built with the same tools
(`sync` after the restore). They are always registered in `SKILL_TOOLS`
order: the list is part of llama.cpp's cached prompt prefix, and the same
skills must give the same list, whether loaded now or restored.
"""

from __future__ import annotations

from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterToolCallEvent

from agent.tools.documents.tool import SKILL_TOOLS

#: Where the skills plugin keeps its state (strands.vended_plugins.skills).
_STATE_KEY = "agent_skills"


def activated(agent: Any) -> list[str]:
    data = agent.state.get(_STATE_KEY)
    return list(data.get("activated_skills", [])) if isinstance(data, dict) else []


class SkillTools(HookProvider):
    """Registers the writing tools of every loaded skill, in a fixed order."""

    def __init__(self, tools: dict[str, Any]) -> None:
        #: The writing tools that are switched on, by name.
        self.tools = tools

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        if event.tool_use.get("name") == "skills" and (event.result or {}).get("status") != "error":
            self.sync(event.agent)

    def sync(self, agent: Any) -> None:
        """The registry holds exactly the loaded skills' tools, in `SKILL_TOOLS` order."""
        wanted: list[str] = []
        loaded = set(activated(agent))
        for skill, names in SKILL_TOOLS.items():
            if skill in loaded:
                wanted += [n for n in names if n in self.tools and n not in wanted]
        registry = agent.tool_registry.registry
        current = [n for n in registry if n in self.tools]
        if current == wanted:
            return
        for name in current:
            registry.pop(name, None)
        for name in wanted:
            agent.tool_registry.register_tool(self.tools[name])


__all__ = ["SkillTools", "activated"]
