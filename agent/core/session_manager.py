"""`SessionManager` (design.md 1a, tests T3.1-T3.3, T3.9).

Atlas keeps **no message content of its own**. Strands stores the messages in
snapshots; Atlas stores the *shape* (the chat tree) and points at snapshot ids.

That is only safe because of a measured property of
`SnapshotSessionManager` (T3.9):

- `save_snapshot(is_latest=False)` writes an **immutable** file, and restoring
  and re-running does not touch it. Verified: after editing turn 3 of 4, all
  four original snapshot files kept their original bytes and mtimes.
- `restore_snapshot` works on snapshots from *discarded* branches, so "editing
  turn 3" never costs us turns 4 and 5. They are off the current path, not gone.
- There is no `append_only` flag. Append-only is what you get from never
  calling `delete_session` and always passing `is_latest=False` for anything
  worth keeping. That is the policy this class enforces.

One instance per chat, and a **new instance per turn**: the session managers
are documented as not thread-safe, and we rebuild the agent every turn anyway
so that LIVE settings apply (design.md L4).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from strands.session import SnapshotSessionManager
from strands.storage import LocalFileStorage

from agent.core.settings import Settings

logger = logging.getLogger(__name__)


class SessionManager:
    """Session policy: where snapshots live, and when Atlas adds one."""

    def __init__(self, settings: Settings, chat_id: str) -> None:
        self.settings = settings
        self.chat_id = chat_id

    # ------------------------------------------------------------ storage --

    def storage_dir(self) -> Path:
        base = Path(self.settings.paths.data_dir) / self.settings.session.dir
        return base

    def manager(self) -> SnapshotSessionManager:
        """A fresh session manager for this chat.

        Fresh per turn, not because the object is expensive but because the docs
        say a session manager is tied to one live agent for one session id, and
        we have a new agent every turn.
        """
        directory = self.storage_dir()
        directory.mkdir(parents=True, exist_ok=True)
        return SnapshotSessionManager(
            session_id=self.chat_id,
            storage=LocalFileStorage(str(directory)),
        )

    # --------------------------------------------------------- snapshots --

    @staticmethod
    async def checkpoint(manager: SnapshotSessionManager, agent: Any) -> str | None:
        """Save an immutable snapshot and return its id.

        `is_latest=False` is the whole point. `is_latest=True` would overwrite
        `snapshot_latest.json` and lose the ability to come back.
        """
        return await manager.save_snapshot(agent, is_latest=False)

    @staticmethod
    async def restore(
        manager: SnapshotSessionManager, agent: Any, snapshot_id: str
    ) -> bool:
        """Rewind the agent's history to a snapshot. False if the id is unknown.

        A missing id is not an error to swallow: it means a snapshot was pruned
        or the tree row is corrupt, and the caller must fail loudly rather than
        continue on whatever history happens to be loaded.
        """
        ok = await manager.restore_snapshot(agent, snapshot_id=snapshot_id)
        if not ok:
            logger.warning(
                "chat=%s | restore_snapshot returned False for %s",
                self.chat_id if hasattr(self, "chat_id") else "?",
                snapshot_id,
            )
        return ok

    @staticmethod
    async def list_snapshots(
        manager: SnapshotSessionManager, agent: Any
    ) -> list[str]:
        """Immutable snapshot ids, oldest first."""
        return await manager.list_snapshot_ids(agent)

    # ------------------------------------------------------------- policy --

    def policy(self) -> dict[str, Any]:
        """The session policy in force, for `GET /settings`."""
        return {
            "dir": str(self.storage_dir()),
            "mode": self.settings.session.mode,
            "max_snapshots": self.settings.session.max_snapshots,
            "delete_session_called": False,
            "immutable_via": "save_snapshot(is_latest=False)",
        }


__all__ = ["SessionManager"]