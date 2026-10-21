"""`MemoryManager`: long-term memory is off, as a decision (docs/decisions.md).

It hands `create_harness` every switch needed to keep memory, and the tools
that come with it, out of the request.

**Why it is off (measured):**

- With a `Model` instance, the harness reuses that same model to distil facts,
  a model call every fifth turn (`IntervalTrigger(turns=5)`).
- Extraction runs in a background task whose failure is swallowed, so a broken
  extractor leaves an empty store that looks exactly like an isolated one. Two
  test runs concluded "no leak" for that reason alone.
- The store is a flat directory of `<slug>.md` files keyed by a slugified first
  line, with no session, chat or branch id, and `add()` appends to an existing
  slug.
- Injection is `trigger="everyTurn"`: entries go into the prompt every turn.

So a fact written in branch A stays on disk, `restore_snapshot` cannot remove
it, and branch B is handed it anyway. Turning memory on needs a design (scope
the store per chat, or filter by branch), not a flag; `MemorySettings` refuses
`enabled: true` for that reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.core import paths
from agent.core.settings import Settings

#: All four are required; `memory=False` alone is not enough.
OFF_SWITCHES: dict[str, Any] = {
    # Harness long-term memory: writes .agent/memory/*.md and retrieves into
    # every turn.
    "memory": False,
    # The harness context manager's "agentic" mode adds a `retrieve_context`
    # tool and offloads bulky tool results to an external stash. The same family
    # of leak as memory: the stash is not part of any snapshot, so restore
    # cannot rewind it.
    "context_manager": False,
    # Vends `strands_manage_background_task`. It survives turning off memory,
    # the context manager, built-in tools and plugins; only this removes it.
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
        """The memory arguments for `create_harness`: always all of `OFF_SWITCHES`."""
        return dict(OFF_SWITCHES)

    def memory_dir(self) -> Path:
        return paths.ROOT / ".agent" / "memory"

    def verify_off(self) -> dict[str, Any]:
        """Check the off-switches actually held: no memory files on disk.

        A switch that stopped working would not error, it would quietly start
        persisting.
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