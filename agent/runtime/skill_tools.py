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

A turn whose message or attachments name a document type starts with that
type's tools already there (`for_message`), and a `write` refused on a .docx
registers the docx tools at once: the model tried `write` on a binary document
before `create_document` in 8 of 19 writing runs, two wasted calls each
(2026-11-12). Loading the skill later keeps them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterToolCallEvent

from agent.tools.documents.tool import SKILL_TOOLS

#: Where the skills plugin keeps its state (strands.vended_plugins.skills).
_STATE_KEY = "agent_skills"

#: The skill whose tools write each kind of file.
_BY_SUFFIX = {".docx": "docx", ".doc": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".xls": "xlsx", ".csv": "xlsx",
              ".pdf": "pdf"}
_NAMED = [(re.compile(r"\b(?:word document|\.?docx?)\b", re.I), "docx"),
          (re.compile(r"\b(?:excel|spreadsheet|workbook|\.?xlsx?)\b", re.I), "xlsx"),
          (re.compile(r"\b\.?pdf\b", re.I), "pdf")]


def for_message(text: str, files: list[str]) -> set[str]:
    """The skills whose tools a message is likely to need: the document types it or its attachments name."""
    found = {_BY_SUFFIX[s] for f in files if (s := Path(f).suffix.lower()) in _BY_SUFFIX}
    return found | {skill for pattern, skill in _NAMED if pattern.search(text or "")}


def activated(agent: Any) -> list[str]:
    data = agent.state.get(_STATE_KEY)
    return list(data.get("activated_skills", [])) if isinstance(data, dict) else []


class SkillTools(HookProvider):
    """Registers the writing tools of every loaded skill, in a fixed order."""

    def __init__(self, tools: dict[str, Any], preload: set[str] | None = None) -> None:
        #: The writing tools that are switched on, by name.
        self.tools = tools
        #: Skills whose tools this turn has without loading them (`for_message`).
        self.preload = set(preload or ())

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._after_tool)

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use.get("name")
        if name == "skills" and (event.result or {}).get("status") != "error":
            self.sync(event.agent)
        elif name in ("write", "edit"):
            # Refused on a binary document (policy._documents): the tool it was told to use is now there.
            skill = _BY_SUFFIX.get(Path(str((event.tool_use.get("input") or {}).get("path", ""))).suffix.lower())
            if skill and skill not in self.preload:
                self.preload.add(skill)
                self.sync(event.agent)

    def sync(self, agent: Any) -> None:
        """The registry holds exactly the loaded skills' tools, in `SKILL_TOOLS` order."""
        wanted: list[str] = []
        loaded = set(activated(agent)) | self.preload
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


__all__ = ["SkillTools", "activated", "for_message"]
