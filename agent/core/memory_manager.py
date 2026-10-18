"""`MemoryManager` (agent/AGENTS.md, docs/decisions.md).

Long-term memory is off, and this class exists to make "off" a decision rather
than an omission. It resolves `memory.enabled` into the harness arguments and
verifies the two switches that actually control the leak.

**Why it is off (measured):**

- With a `Model` instance, the harness reuses **that same model** to distil
  facts, so extraction is a model call on every fifth turn
  (`IntervalTrigger(turns=5)`).
- Extraction runs in a **background task whose failure is swallowed**. A stub
  that raised `NotImplementedError` from `structured_output` produced a
  completely empty memory store -- indistinguishable, from the outside, from
  "memory is on and correctly isolated". Two separate test runs concluded
  "no leak" for that reason alone.
- The store is a flat directory of `<slug>.md` files. The key is derived from a
  slugified first line. There is no session id, chat id or branch id anywhere in
  the path or the key, and `add()` **appends** to an existing slug rather than
  replacing it.
- Injection is `trigger="everyTurn"`: retrieved entries go into the prompt on
  every turn, whether or not the model asked.

So a fact written in branch A is on disk permanently, `restore_snapshot` cannot
remove it (it is not in the snapshot), and branch B is handed it anyway. Branch
isolation and long-term memory are structurally incompatible as shipped.

Turning this on later needs a design -- scope the store per chat, or filter
retrieval by the current branch -- not just flipping the flag. `MemorySettings`
refuses `enabled: true` at validation for the same reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core import paths
from agent.core.settings import Settings

#: The switches that matter. All four are required; the comment on each says
#: what it stops, because "we set memory=False" is not sufficient on its own.
OFF_SWITCHES: dict[str, Any] = {
    # Harness long-term memory: writes .agent/memory/*.md and retrieves into
    # every turn. The original leak.
    "memory": False,
    # The harness context manager's "agentic" mode adds a `retrieve_context`
    # tool and offloads bulky tool results to an external stash. The same family
    # of leak as memory: the stash is not part of any snapshot, so restore
    # cannot rewind it.
    "context_manager": False,
    # Vends `strands_manage_background_task`. Not a memory feature by name, but
    # it survived turning off memory, the context manager, built-in tools and
    # plugins -- the documented four-switch shutdown was not enough, and only
    # `background_tasks=False` removes it.
    "background_tasks": False,
    # The `todos` plugin vends `todo_write`; `environment` vends its own tools.
    # Neither is persistent, but every tool schema costs prompt tokens.
    "builtin_plugins": [],
}


class MemoryManager:
    """Resolves `memory.enabled` into the harness's memory arguments."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def harness_args(self) -> dict[str, Any]:
        """The memory-related arguments for `create_harness`.

        Always the full off-switch set. `MemorySettings` already rejects
        `enabled: true` at validation, so there is no branch here to get wrong.
        """
        return dict(OFF_SWITCHES)

    def memory_dir(self) -> Path:
        return paths.ROOT / ".agent" / "memory"

    def verify_off(self) -> dict[str, Any]:
        """Check the off-switches actually held. Cheap, so it runs every turn.

        Worth it because the failure is invisible: a switch that stopped
        working would not error, it would quietly start persisting.
        """
        directory = self.memory_dir()
        files = sorted(p.name for p in directory.rglob("*") if p.is_file()) \
            if directory.exists() else []
        return {
            "memory_enabled": self.settings.memory.enabled,
            "switches": {k: v for k, v in OFF_SWITCHES.items()},
            "memory_dir": str(directory),
            "files_present": files,
            "clean": not files and not self.settings.memory.enabled,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.memory.enabled,
            "reason": (
                "the file memory store is not scoped to a chat or a branch, so "
                "facts written in one branch are injected into every other "
                "branch on every turn"
            ),
        }


__all__ = ["MemoryManager", "OFF_SWITCHES"]