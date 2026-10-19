"""The chat tree: its shape, and a display transcript per turn.

Two tables:

    chats(id, title, selected_root, created_at, updated_at)
    turns(id, chat_id, parent_turn_id, user_text, files_json,
          before_snap, after_snap, status, selected_child,
          render_json, stats_json, error, created_at)

`before_snap` and `after_snap` are Strands snapshot ids, and the snapshots are
the model's history -- the only copy, owned by Strands. `render_json` is what
the *UI* showed for the turn: answer text, reasoning, tool cards with their
results. It is written once when a run ends and never fed back to the model.
It exists so opening a chat is one query instead of replaying a snapshot per
turn, and so reasoning (which Strands never stores) survives a reload.

**The two operations that change the past, and why they differ:**

*Retry* is non-destructive and only allowed on the last turn of the visible
path. It adds a sibling version with the same parent and the same restore
point. Versions are independent branches: every version keeps its own
follow-ups, and `<` / `>` stays usable on any turn that has more than one.

*Edit* is destructive and allowed on any turn. The edited turn, every sibling
version of it, and everything below all of them are deleted -- rows here and
snapshots in Strands' storage -- and the new turn takes their place under the
same parent. An edit rewrites history from that point; keeping the old future
around would mean keeping answers to a question that was never asked.

**Rules kept from before:**

*Only a completed turn can be a parent.* A half-finished tool call must never
be baked into the history a follow-up builds on.

*Sends branch from the selected leaf*, not from whatever turn was on screen
when typing started. Otherwise a send after switching versions silently forks.

*Roots are siblings of each other.* A root has no parent row to hold
`selected_child`, so the chat holds `selected_root`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, INTERRUPTED})

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT '',
    selected_root TEXT,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id             TEXT PRIMARY KEY,
    chat_id        TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    parent_turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
    user_text      TEXT NOT NULL,
    files_json     TEXT NOT NULL DEFAULT '[]',
    before_snap    TEXT,
    after_snap     TEXT,
    status         TEXT NOT NULL DEFAULT 'running',
    selected_child TEXT,
    render_json    TEXT,
    stats_json     TEXT,
    refs_json      TEXT NOT NULL DEFAULT '[]',
    error          TEXT,
    created_at     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_chat ON turns(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_parent ON turns(parent_turn_id);
"""


def new_id() -> str:
    return uuid.uuid4().hex


def _now() -> int:
    """Epoch milliseconds, which is what every `created_at` is."""
    return int(time.time() * 1000)


class TreeError(Exception):
    """An operation the tree rules forbid. The API turns it into a 409."""


class ChatStore:
    """SQLite-backed tree. One connection, a lock, short queries.

    WAL mode so a reader never blocks on the writer, and `close()` is called on
    shutdown: a connection held open by a process that outlived its terminal
    was what kept `atlas.db` locked (EBUSY) after a stop.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            # Columns added after a database was created. CREATE TABLE IF NOT
            # EXISTS does not evolve an existing table.
            have = {r["name"] for r in self._conn.execute("PRAGMA table_info(turns)")}
            if "refs_json" not in have:
                self._conn.execute("ALTER TABLE turns ADD COLUMN refs_json TEXT NOT NULL DEFAULT '[]'")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _row(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _write(self, *statements: tuple[str, tuple]) -> None:
        with self._lock:
            for sql, args in statements:
                self._conn.execute(sql, args)
            self._conn.commit()

    # ------------------------------------------------------------- chats --

    def create_chat(self, title: str = "") -> dict[str, Any]:
        cid, now = new_id(), _now()
        self._write(("INSERT INTO chats(id, title, created_at, updated_at) VALUES(?,?,?,?)",
                     (cid, title, now, now)))
        return self.get_chat(cid)  # type: ignore[return-value]

    def list_chats(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM chats ORDER BY updated_at DESC")

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM chats WHERE id=?", (chat_id,))

    def set_title(self, chat_id: str, title: str, *, only_if_empty: bool = False) -> None:
        sql = "UPDATE chats SET title=? WHERE id=?" + (" AND title=''" if only_if_empty else "")
        self._write((sql, (title, chat_id)))

    def touch(self, chat_id: str) -> None:
        self._write(("UPDATE chats SET updated_at=? WHERE id=?", (_now(), chat_id)))

    def delete_chat(self, chat_id: str) -> list[str]:
        """Delete the chat's rows. Returns its snapshot ids for the caller to remove."""
        snaps = self._snapshots_of([t["id"] for t in self._rows(
            "SELECT id FROM turns WHERE chat_id=?", (chat_id,))])
        self._write(("DELETE FROM turns WHERE chat_id=?", (chat_id,)),
                    ("DELETE FROM chats WHERE id=?", (chat_id,)))
        return snaps

    # ------------------------------------------------------------- turns --

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM turns WHERE id=?", (turn_id,))

    def insert_turn(
        self,
        chat_id: str,
        user_text: str,
        *,
        parent_turn_id: str | None,
        before_snap: str | None,
        files: list[dict[str, Any]] | None = None,
        refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Insert a turn and make it the selected version at its position.

        `refs` are passages the user selected in the preview panel and attached
        to this question: `{"file", "path", "quote"}`.
        """
        tid, now = new_id(), _now()
        select = (("UPDATE turns SET selected_child=? WHERE id=?", (tid, parent_turn_id))
                  if parent_turn_id else
                  ("UPDATE chats SET selected_root=? WHERE id=?", (tid, chat_id)))
        self._write(
            ("""INSERT INTO turns(id, chat_id, parent_turn_id, user_text, files_json,
                                  refs_json, before_snap, status, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
             (tid, chat_id, parent_turn_id, user_text, json.dumps(files or []),
              json.dumps(refs or []), before_snap, RUNNING, now)),
            select,
            ("UPDATE chats SET updated_at=? WHERE id=?", (now, chat_id)),
        )
        return self.get_turn(tid)  # type: ignore[return-value]

    def finish_turn(
        self,
        turn_id: str,
        status: str,
        *,
        after_snap: str | None = None,
        render: list[dict[str, Any]] | None = None,
        stats: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in TERMINAL:
            raise ValueError(f"unknown terminal status {status!r}")
        self._write(("""UPDATE turns SET status=?, after_snap=?, render_json=?,
                                         stats_json=?, error=? WHERE id=?""",
                     (status, after_snap,
                      None if render is None else json.dumps(render),
                      None if stats is None else json.dumps(stats),
                      error, turn_id)))

    def mark_interrupted(self) -> int:
        """Turns left `running` by a crash become `interrupted`; retry recovers them."""
        with self._lock:
            n = self._conn.execute("UPDATE turns SET status=? WHERE status=?",
                                   (INTERRUPTED, RUNNING)).rowcount
            self._conn.commit()
        return n

    # ------------------------------------------------------------ siblings --

    def siblings_of(self, turn_id: str) -> list[dict[str, Any]]:
        """Every version at this turn's position, oldest first."""
        turn = self.get_turn(turn_id)
        if turn is None:
            return []
        if turn["parent_turn_id"] is not None:
            return self._rows("SELECT * FROM turns WHERE parent_turn_id=? ORDER BY created_at",
                              (turn["parent_turn_id"],))
        return self._rows("""SELECT * FROM turns WHERE chat_id=? AND parent_turn_id IS NULL
                             ORDER BY created_at""", (turn["chat_id"],))

    def select(self, turn_id: str) -> None:
        """Make this version the selected one at its position."""
        turn = self.get_turn(turn_id)
        if turn is None:
            raise TreeError(f"no turn {turn_id}")
        if turn["parent_turn_id"]:
            self._write(("UPDATE turns SET selected_child=? WHERE id=?",
                         (turn_id, turn["parent_turn_id"])))
        else:
            self._write(("UPDATE chats SET selected_root=? WHERE id=?",
                         (turn_id, turn["chat_id"])))

    # --------------------------------------------------------------- walk --

    def path(self, chat_id: str) -> list[dict[str, Any]]:
        """Root to leaf, following each selected version. The visible chat."""
        chat = self.get_chat(chat_id)
        if chat is None:
            return []
        row = self.get_turn(chat["selected_root"]) if chat["selected_root"] else None
        out: list[dict[str, Any]] = []
        while row is not None and row["chat_id"] == chat_id:
            out.append(row)
            row = self.get_turn(row["selected_child"]) if row["selected_child"] else None
        return out

    def leaf(self, chat_id: str) -> dict[str, Any] | None:
        path = self.path(chat_id)
        return path[-1] if path else None

    def is_leaf(self, turn_id: str) -> bool:
        turn = self.get_turn(turn_id)
        leaf = self.leaf(turn["chat_id"]) if turn else None
        return bool(leaf and leaf["id"] == turn_id)

    def subtree(self, turn_id: str) -> list[str]:
        """Every turn id under `turn_id`, including itself."""
        out, stack = [], [turn_id]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(r["id"] for r in self._rows(
                "SELECT id FROM turns WHERE parent_turn_id=?", (current,)))
        return out

    # ------------------------------------------------------------ edit/cut --

    def cut_from(self, turn_id: str) -> tuple[dict[str, Any], list[str]]:
        """Delete a turn, all its versions, and everything below them.

        Returns the deleted turn (whose parent and `before_snap` the edit
        reuses) and every snapshot id that belonged to the deleted turns. The
        `before_snap` itself is the parent's `after_snap` and is never in that
        list -- it still belongs to the parent.
        """
        turn = self.get_turn(turn_id)
        if turn is None:
            raise TreeError(f"no turn {turn_id}")
        doomed: list[str] = []
        for version in self.siblings_of(turn_id):
            doomed.extend(self.subtree(version["id"]))
        snaps = self._snapshots_of(doomed)
        marks = ",".join("?" * len(doomed))
        clear_pointer = (("UPDATE turns SET selected_child=NULL WHERE id=?", (turn["parent_turn_id"],))
                         if turn["parent_turn_id"] else
                         ("UPDATE chats SET selected_root=NULL WHERE id=?", (turn["chat_id"],)))
        # Children before parents is not needed: ON DELETE CASCADE and one
        # statement over the whole set.
        self._write(clear_pointer, (f"DELETE FROM turns WHERE id IN ({marks})", tuple(doomed)))
        return turn, snaps

    # ------------------------------------------------------ export/import --

    def export_rows(self, chat_id: str) -> dict[str, Any]:
        chat = self.get_chat(chat_id)
        turns = self._rows("SELECT * FROM turns WHERE chat_id=? ORDER BY created_at", (chat_id,))
        return {"chat": chat, "turns": turns}

    def import_rows(self, chat: dict[str, Any], turns: list[dict[str, Any]]) -> str:
        """Insert an exported chat under fresh ids. Returns the new chat id.

        Ids are remapped so importing the same file twice gives two chats
        rather than a primary-key collision. Snapshot ids are kept: they are
        stored under the new chat's session, so they cannot clash either.
        """
        new_chat = new_id()
        ids = {t["id"]: new_id() for t in turns}
        now = _now()
        statements: list[tuple[str, tuple]] = [(
            "INSERT INTO chats(id, title, selected_root, created_at, updated_at) VALUES(?,?,?,?,?)",
            (new_chat, chat.get("title") or "Imported chat", ids.get(chat.get("selected_root")),
             chat.get("created_at") or now, now))]
        for t in turns:  # created_at order, so a parent is always inserted first
            statements.append((
                """INSERT INTO turns(id, chat_id, parent_turn_id, user_text, files_json,
                                     refs_json, before_snap, after_snap, status, selected_child,
                                     render_json, stats_json, error, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ids[t["id"]], new_chat, ids.get(t.get("parent_turn_id")), t.get("user_text", ""),
                 t.get("files_json") or "[]", t.get("refs_json") or "[]",
                 t.get("before_snap"), t.get("after_snap"),
                 t["status"] if t.get("status") in TERMINAL else INTERRUPTED,
                 ids.get(t.get("selected_child")), t.get("render_json"), t.get("stats_json"),
                 t.get("error"), t.get("created_at") or now)))
        self._write(*statements)
        return new_chat

    def _snapshots_of(self, turn_ids: list[str]) -> list[str]:
        if not turn_ids:
            return []
        marks = ",".join("?" * len(turn_ids))
        rows = self._rows(f"SELECT after_snap FROM turns WHERE id IN ({marks})", tuple(turn_ids))
        return [r["after_snap"] for r in rows if r["after_snap"]]


__all__ = [
    "CANCELLED",
    "COMPLETED",
    "ChatStore",
    "FAILED",
    "INTERRUPTED",
    "RUNNING",
    "SCHEMA",
    "TERMINAL",
    "TreeError",
    "new_id",
]
