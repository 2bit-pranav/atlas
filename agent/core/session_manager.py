"""`SessionManager`: where Strands keeps a chat's snapshots.

Atlas stores no model history of its own. Strands writes every message into
snapshots; Atlas's chat tree stores only snapshot *ids* (`before_snap`,
`after_snap`) and points at them. Restoring, saving and deleting are all
Strands' own operations -- this class only decides where the files go and
which ones to remove.

Properties of `SnapshotSessionManager` this relies on, measured:

- `save_snapshot(is_latest=False)` writes an **immutable** file under a fresh,
  time-ordered id, and restoring and re-running does not touch it.
- `restore_snapshot` works on any of those ids, so retry siblings are
  independent: switching versions is a restore, never a recomputation.

Deletion exists for exactly two cases: an edit, which discards everything after
the edited turn, and deleting a whole chat. Both remove the files through the
storage object Strands itself reads from, so the key layout is never guessed.

One instance per chat, and a **new Strands manager per turn**: the session
managers are documented as not thread-safe, and the agent is rebuilt every turn
anyway so LIVE settings apply.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from strands.session import SnapshotSessionManager
from strands.session.snapshot_session_manager import _snapshot_key
from strands.storage import LocalFileStorage

from agent.core import paths
from agent.core.settings import Settings

logger = logging.getLogger(__name__)

#: The agent id the harness builds its agent with. Snapshot keys include it.
AGENT_ID = "default"


class SessionManager:
    """Session policy: where snapshots live, and which ones to delete."""

    def __init__(self, settings: Settings, chat_id: str) -> None:
        self.settings = settings
        self.chat_id = chat_id

    def storage_dir(self) -> Path:
        return paths.sessions_dir(self.settings)

    def manager(self) -> SnapshotSessionManager:
        """A fresh Strands session manager for this chat."""
        directory = self.storage_dir()
        directory.mkdir(parents=True, exist_ok=True)
        return SnapshotSessionManager(
            session_id=self.chat_id,
            storage=LocalFileStorage(str(directory)),
            # Never write `snapshot_latest`. Strands restores it automatically
            # when an agent starts, so a turn with no restore point (any root
            # turn: a first message, or a retry or edit of one) would silently
            # begin with the previous conversation loaded. Atlas always names
            # the snapshot it restores, so "latest" is never wanted.
            save_latest_on="trigger",
        )

    async def delete_snapshots(self, snapshot_ids: Iterable[str | None]) -> int:
        """Remove immutable snapshots by id. Returns how many were removed.

        A missing file is not an error: a cancelled or failed turn never wrote
        an `after_snap`, and deleting nothing is the right outcome.
        """
        ids = sorted({s for s in snapshot_ids if s})
        if not ids:
            return 0
        storage = self.manager()._resolved_storage  # noqa: SLF001 - Strands' own view
        removed = 0
        for snapshot_id in ids:
            try:
                await storage.delete(_snapshot_key(self.chat_id, AGENT_ID, snapshot_id=snapshot_id))
                removed += 1
            except FileNotFoundError:
                continue
            except Exception:  # noqa: BLE001 - a stray file costs disk, not correctness
                logger.warning("chat=%s | could not delete snapshot %s", self.chat_id, snapshot_id,
                               exc_info=True)
        return removed

    async def read_snapshots(self, snapshot_ids: Iterable[str | None]) -> dict[str, str]:
        """Snapshot bytes by id, as text, for an export. Missing ids are skipped."""
        storage = self.manager()._resolved_storage  # noqa: SLF001
        out: dict[str, str] = {}
        for snapshot_id in sorted({s for s in snapshot_ids if s}):
            data = await storage.read(_snapshot_key(self.chat_id, AGENT_ID, snapshot_id=snapshot_id))
            if data is not None:
                out[snapshot_id] = data.decode("utf-8")
        return out

    async def write_snapshots(self, snapshots: dict[str, str]) -> None:
        """Write exported snapshots back under this chat's session, for an import."""
        storage = self.manager()._resolved_storage  # noqa: SLF001
        for snapshot_id, text in snapshots.items():
            await storage.write(_snapshot_key(self.chat_id, AGENT_ID, snapshot_id=snapshot_id),
                                text.encode("utf-8"))

    async def delete_all(self) -> None:
        """Remove every snapshot of this chat. Used when the chat is deleted."""
        await self.manager().delete_session()

    def policy(self) -> dict[str, Any]:
        """The session policy in force, for `GET /settings`."""
        return {"dir": str(self.storage_dir()), "immutable_via": "save_snapshot(is_latest=False)"}


__all__ = ["AGENT_ID", "SessionManager"]
