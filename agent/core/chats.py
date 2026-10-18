"""The chat tree (design.md L3). Shape only; Strands owns the messages.

Two tables. That is the entire Atlas-owned schema, and it is small because
every measured property of `SnapshotSessionManager` (T3.9) lets message content
live in Strands:

    chats(id, title, created_at)
    turns(id, chat_id, parent_turn_id, user_text, files_json,
          before_snap, after_snap, status, selected_child, created_at)

`before_snap` and `after_snap` are Strands snapshot ids. Nothing else about a
conversation is stored here.

**The rules, and why each one is not optional:**

*Never delete.* Snapshots written with `is_latest=False` are immutable, and
restore works on snapshots from abandoned branches. So editing turn 3 of 5
does not cost turns 4 and 5: they are off the current path, not gone.

*`selected_child` is the only thing that moves.* Editing an earlier turn
creates a sibling and points the parent's `selected_child` at it. Depth is
irrelevant -- editing turn 1 and editing turn 5 run identical code. Nothing is
invalidated and nothing cascades.

*Roots have their own grouping.* A root turn has no parent to hang siblings
off, so root versions live in a `root_group` column. Without it `<`/`>` at the
first message has nothing to walk between. This was not theoretical: the first
attempt returned `KeyError: None`, then a duplicate-roots bug.

*Sending branches from the selected child.* A new message goes on top of
whatever turn is currently selected, not on top of the turn it was typed after.
Otherwise sending after an edit silently splits the conversation.

*Restore points are the parent's `after_snap`.* A follow-up restores from the
state after the turn it sits under, not from a shared "before" point. Getting
this wrong replays a turn twice.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

#: A turn that finished. Only a completed turn may be the parent of a new send,
#: so a half-finished tool call can never be baked into the history.
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED})

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    selected_root TEXT REFERENCES turns(id),
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id            TEXT PRIMARY KEY,
    chat_id       TEXT NOT NULL REFERENCES chats(id),
    parent_turn_id TEXT REFERENCES turns(id),
    user_text     TEXT NOT NULL,
    files_json    TEXT NOT NULL DEFAULT '[]',
    before_snap   TEXT,
    after_snap    TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    selected_child TEXT,
    root_group    INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_chat ON turns(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_parent ON turns(parent_turn_id);
"""


def new_id() -> str:
    """Sortable id: ULID-ish. Time-ordered, so ORDER BY id is chronological."""
    return uuid.uuid4().hex


class ChatStore:
    """SQLite-backed tree. One connection, a lock, short queries.

    Not a repository framework and not a database design -- two tables and the
    tree walk. The old build had seven migrations and a repository layer; this
    iteration needs neither, and the schema is small enough to read in one
    sitting.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        with self._lock:
            self._conn.executescript(SCHEMA)
            # Existing databases predate selected_root. SQLite's CREATE TABLE
            # IF NOT EXISTS does not evolve them, so make this small migration
            # explicit rather than silently leaving root version selection
            # broken for every existing chat.
            columns = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(chats)")
            }
            if "selected_root" not in columns:
                self._conn.execute("ALTER TABLE chats ADD COLUMN selected_root TEXT")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- chats --

    def create_chat(self, title: str = "") -> dict[str, Any]:
        cid = new_id()
        with self._lock:
            self._conn.execute(
                "INSERT INTO chats(id, title, created_at) VALUES(?,?,?)",
                (cid, title, int(time.time() * 1000)),
            )
            self._conn.commit()
        return {"id": cid, "title": title}

    def list_chats(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM chats ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM chats WHERE id=?", (chat_id,)
            ).fetchone()
        return dict(row) if row else None

    def set_title(self, chat_id: str, title: str) -> None:
        """Name a chat. Only ever called when the title is still empty."""
        with self._lock:
            self._conn.execute(
                "UPDATE chats SET title=? WHERE id=? AND title=''",
                (title, chat_id),
            )
            self._conn.commit()

    def delete_chat(self, chat_id: str) -> None:
        """Deletes the tree rows only. Snapshots on disk are left alone.

        Deliberately: `delete_session` is never called anywhere in Atlas. If a
        snapshot file outlives its chat that wastes disk; deleting the wrong one
        would break a restore that some other chat row still points at.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM turns WHERE chat_id=?", (chat_id,)
            )
            self._conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
            self._conn.commit()

    # ------------------------------------------------------------- turns --

    def insert_turn(
        self,
        chat_id: str,
        user_text: str,
        *,
        parent_turn_id: str | None,
        before_snap: str | None,
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tid = new_id()
        with self._lock:
            root_group = 0 if parent_turn_id is None else self._next_root_group(
                chat_id, parent_turn_id
            )
            self._conn.execute(
                """INSERT INTO turns(id, chat_id, parent_turn_id, user_text,
                                      files_json, before_snap, status,
                                      root_group, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    tid,
                    chat_id,
                    parent_turn_id,
                    user_text,
                    json.dumps(files or []),
                    before_snap,
                    RUNNING,
                    root_group,
                    int(time.time() * 1000),
                ),
            )
            if parent_turn_id:
                self._conn.execute(
                    "UPDATE turns SET selected_child=? WHERE id=?",
                    (tid, parent_turn_id),
                )
            else:
                # Root turns are siblings too, but have no parent row on which
                # to store selected_child. The chat owns that one pointer.
                self._conn.execute(
                    "UPDATE chats SET selected_root=? WHERE id=?", (tid, chat_id)
                )
            self._conn.commit()
        turn = self.get_turn(tid)
        assert turn is not None
        return turn

    def _next_root_group(self, chat_id: str, parent_turn_id: str) -> int:
        """Siblings of `parent_turn_id` are one group; a child is its own."""
        row = self._conn.execute(
            "SELECT root_group FROM turns WHERE id=?", (parent_turn_id,)
        ).fetchone()
        parent_group = row["root_group"] if row else 0
        # A non-root turn is its own group: only true roots share a group, and
        # that is decided by having no parent at all.
        parent_has_parent = self._conn.execute(
            "SELECT 1 FROM turns WHERE id=? AND parent_turn_id IS NOT NULL",
            (parent_turn_id,),
        ).fetchone()
        return parent_group if not parent_has_parent else 0

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM turns WHERE id=?", (turn_id,)
            ).fetchone()
        return dict(row) if row else None

    def set_status(
        self, turn_id: str, status: str, *, after_snap: str | None = None
    ) -> None:
        if status not in TERMINAL | {RUNNING}:
            raise ValueError(f"unknown status {status!r}")
        with self._lock:
            if after_snap is None:
                self._conn.execute(
                    "UPDATE turns SET status=? WHERE id=?", (status, turn_id)
                )
            else:
                self._conn.execute(
                    "UPDATE turns SET status=?, after_snap=? WHERE id=?",
                    (status, after_snap, turn_id),
                )
            self._conn.commit()

    def select_child(self, turn_id: str, child_id: str | None) -> None:
        """Point a turn's `selected_child` at a sibling version. `<` / `>`."""
        with self._lock:
            self._conn.execute(
                "UPDATE turns SET selected_child=? WHERE id=?",
                (child_id, turn_id),
            )
            self._conn.commit()

    def children_of(self, turn_id: str) -> list[dict[str, Any]]:
        """Turns whose `parent_turn_id` is this one.

        Only ever children. Siblings of a root turn are *not* children of it,
        and conflating the two makes `subtree` walk sideways -- which is how
        the first version of this returned another root's whole conversation
        when asked for the children of a root.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM turns WHERE parent_turn_id=? ORDER BY created_at",
                (turn_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def siblings_of(self, turn_id: str) -> list[dict[str, Any]]:
        """Every version of this turn's position, in creation order.

        This is the list `<` and `>` walk. It is never filtered by status: a
        cancelled version stays selectable, because "what did I just cancel?" is
        a real question and it costs nothing to answer.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT chat_id, parent_turn_id, root_group FROM turns WHERE id=?",
                (turn_id,),
            ).fetchone()
            if row is None:
                return []
            if row["parent_turn_id"] is not None:
                rows = self._conn.execute(
                    "SELECT * FROM turns WHERE parent_turn_id=? ORDER BY created_at",
                    (row["parent_turn_id"],),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT * FROM turns
                       WHERE chat_id=? AND parent_turn_id IS NULL AND root_group=?
                       ORDER BY created_at""",
                    (row["chat_id"], row["root_group"]),
                ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- walk --

    def path(self, chat_id: str) -> list[dict[str, Any]]:
        """Root to leaf, following `selected_child`. The visible conversation."""
        with self._lock:
            selected = self._conn.execute(
                "SELECT selected_root FROM chats WHERE id=?", (chat_id,)
            ).fetchone()
            row = None
            if selected and selected["selected_root"]:
                row = self._conn.execute(
                    "SELECT * FROM turns WHERE id=? AND chat_id=?",
                    (selected["selected_root"], chat_id),
                ).fetchone()
            # Backward-compatible fallback for a chat created before the
            # selected_root column existed.
            if row is None:
                row = self._conn.execute(
                    """SELECT * FROM turns
                       WHERE chat_id=? AND parent_turn_id IS NULL AND root_group=0
                       ORDER BY created_at DESC LIMIT 1""",
                    (chat_id,),
                ).fetchone()
            if row is None:
                return []
            out = [dict(row)]
            while True:
                child = out[-1].get("selected_child")
                if not child:
                    break
                nxt = self._conn.execute(
                    "SELECT * FROM turns WHERE id=?", (child,)
                ).fetchone()
                if nxt is None:
                    # A dangling pointer means the row was pruned. Stop rather
                    # than loop or crash; the caller sees a short path.
                    break
                out.append(dict(nxt))
        return out

    def walk_sibling(self, turn_id: str, delta: int) -> dict[str, Any] | None:
        """Move `<` (delta -1) or `>` (delta +1) among a turn's versions.

        Clamped at the ends rather than wrapping: wrapping makes "back" from
        the first version jump to the last, which reads as a bug.
        """
        versions = self.siblings_of(turn_id)
        if not versions:
            return self.get_turn(turn_id)
        ids = [v["id"] for v in versions]
        if turn_id not in ids:
            return self.get_turn(turn_id)
        index = max(0, min(ids.index(turn_id) + delta, len(ids) - 1))
        return versions[index]

    def select_root(self, chat_id: str, root_id: str) -> None:
        """Select a root version. Root siblings have no parent turn."""
        with self._lock:
            self._conn.execute(
                "UPDATE chats SET selected_root=? WHERE id=?", (root_id, chat_id)
            )
            self._conn.commit()

    def subtree(self, turn_id: str) -> list[str]:
        """Every turn id under `turn_id`, including itself."""
        out: list[str] = []
        stack = [turn_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            out.append(current)
            stack.extend(c["id"] for c in self.children_of(current))
        return sorted(out)

    def subtree_size(self, turn_id: str) -> int:
        return len(self.subtree(turn_id))

    def interrupted_running_turns(self) -> list[dict[str, Any]]:
        """Turns left `running` by a backend crash. Retry is the recovery."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM turns WHERE status=?", (RUNNING,)
            ).fetchall()
        return [dict(r) for r in rows]

    def leaf(self, chat_id: str) -> dict[str, Any] | None:
        path = self.path(chat_id)
        return path[-1] if path else None


__all__ = [
    "CANCELLED",
    "COMPLETED",
    "ChatStore",
    "FAILED",
    "INTERRUPTED",
    "RUNNING",
    "SCHEMA",
    "TERMINAL",
    "new_id",
]
