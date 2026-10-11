"""ToolRuntime (spec section 11): builds the tool set for a run.

Per-run by design. The agent is fresh each run (section 9), and so is this:
every tool reads its context out of ``invocation_state`` rather than from
instance state, so there is no way for one run's context to leak into another's.

Tools are registered up front and never change during a run. That keeps the
prompt prefix byte-stable, which is what preserves llama.cpp's prompt cache
(section 10) -- adding a tool mid-run would invalidate it.

The skill gate (section 9.1) hooks in here too, so a skill's tools are visible
from the start but cannot be *called* until the model has activated the skill.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.core.repo import Repo
from agent.ingest.registry import registry as ingest_registry
from agent.tools import core_tools
from agent.tools.context import ToolContext

logger = logging.getLogger(__name__)


class ToolRuntime:
    """Assembles the agent's tools and the per-run context."""

    #: Always-on core. Order is the order the model sees them in.
    CORE = (
        core_tools.list_files,
        core_tools.outline,
        core_tools.read,
        core_tools.search,
        core_tools.describe,
        core_tools.query,
        core_tools.show,
        core_tools.collect,
        core_tools.plan,
        core_tools.note,
    )

    def __init__(
        self,
        repo: Repo,
        *,
        workspace_root: Path | None = None,
        settings: dict[str, Any] | None = None,
        skill_tools: list[Any] | None = None,
    ) -> None:
        self.repo = repo
        self.workspace_root = workspace_root
        self.settings = settings or {}
        self._skill_tools = list(skill_tools or [])

    # ------------------------------------------------------------------ tools --

    def tools(self) -> list[Any]:
        """Every tool visible to the model, for the whole run."""
        return [*self.CORE, *self._skill_tools]

    def core_names(self) -> list[str]:
        return [getattr(t, "tool_name", getattr(t, "__name__", "?")) for t in self.CORE]

    # --------------------------------------------------------------- context --

    def context_for(
        self,
        *,
        run: Any,
        chat_id: str,
        node_id: str,
        cancel: Any = None,
        emit: Any = None,
    ) -> ToolContext:
        from agent.core.paths import resolve_chat_dir

        workspace = (
            Path(self.workspace_root) / chat_id
            if self.workspace_root is not None
            else resolve_chat_dir() / chat_id
        )
        workspace.mkdir(parents=True, exist_ok=True)
        ctx = ToolContext(
            repo=self.repo,
            run=run,
            chat_id=chat_id,
            node_id=node_id,
            workspace=workspace,
            settings=self.settings,
            emit=emit,
        )
        if cancel is not None:
            ctx.cancel = cancel
        return ctx


__all__ = ["ToolRuntime"]
