"""Repository layer: chats, the node tree, runs, and the event log.

Implements the interface section 19 asks L2 for:

    Repo.start_run(...)      one guarded path for send / edit / retry
    Repo.visible_path(chat)  root + selected_child_id chain to the leaf
    Repo.append_event(...)   gap-free seq from 1
    Repo.finalize_run(...)   terminal event + status + node, ONE transaction

The tree rules from sections 5 and 6:

* every chat has a synthetic ``root`` node, so editing the first message is an
  ordinary sibling operation;
* the visible path is root then ``selected_child_id`` to the leaf, so switching
  versions updates exactly one column;
* a new user message attaches only to root or to an assistant node whose run
  completed - a cancelled or failed node stays put so it can be retried, but
  cannot be a parent in v1;
* the global one-run lock is the database's partial unique index, so two
  concurrent starts cannot both succeed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from agent.core.db import Database, is_unique_violation
from agent.core.errors import (
    BadRequest,
    NotFound,
    ParentNotAccepting,
    RunActive,
    RunFinished,
    TerminalEventExists,
)
from agent.ids import new_ulid, now_ms

TERMINAL_EVENT_TYPES = ("run_completed", "run_failed", "run_cancelled")
ACTIVE_STATUSES = ("running", "cancelling")
COMPLETABLE_STATUSES = ("completed",)


# ------------------------------------------------------------------- records --


@dataclass(frozen=True)
class Chat:
    id: str
    title: str | None
    root_id: str
    created_at: int
    updated_at: int
    deleted_at: int | None


@dataclass(frozen=True)
class Node:
    id: str
    chat_id: str
    parent_id: str | None
    role: str
    content: Any
    run_id: str | None
    selected_child_id: str | None
    task_state: Any
    created_at: int

    @property
    def is_root(self) -> bool:
        return self.role == "root"


@dataclass(frozen=True)
class Run:
    id: str
    chat_id: str
    user_node_id: str | None
    assistant_node_id: str | None
    origin: str
    status: str
    options: Any
    settings_snapshot: Any
    launch_id: str | None
    error: Any
    usage: Any
    context_stats: Any
    last_seq: int
    started_at: int
    finished_at: int | None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


@dataclass(frozen=True)
class Event:
    run_id: str
    seq: int
    ts: int
    type: str
    payload: Any

    @property
    def is_terminal(self) -> bool:
        return self.type in TERMINAL_EVENT_TYPES


@dataclass(frozen=True)
class Step:
    id: str
    node_id: str
    idx: int
    kind: str
    content: Any
    call_id: str | None
    is_error: bool
    status: str
    tokens: int
    object_id: str | None


@dataclass(frozen=True)
class CatalogObject:
    id: str
    chat_id: str
    run_id: str | None
    step_id: str | None
    node_id: str | None
    name: str
    kind: str
    store: str
    schema: Any
    row_count: int | None
    tokens: int | None
    provenance: Any
    created_at: int


@dataclass(frozen=True)
class TreeNode:
    """A node plus what the UI needs to offer the `<` `>` version switch."""

    node: Node
    siblings: list[Node] = field(default_factory=list)
    sibling_index: int = 0

    @property
    def sibling_count(self) -> int:
        return len(self.siblings)


# ------------------------------------------------------------------- helpers --


def _loads(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _chat(row: sqlite3.Row) -> Chat:
    return Chat(
        id=row["id"], title=row["title"], root_id=row["root_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _node(row: sqlite3.Row) -> Node:
    return Node(
        id=row["id"], chat_id=row["chat_id"], parent_id=row["parent_id"],
        role=row["role"], content=_loads(row["content"]), run_id=row["run_id"],
        selected_child_id=row["selected_child_id"],
        task_state=_loads(row["task_state"]), created_at=row["created_at"],
    )


def _run(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"], chat_id=row["chat_id"], user_node_id=row["user_node_id"],
        assistant_node_id=row["assistant_node_id"], origin=row["origin"],
        status=row["status"], options=_loads(row["options"]),
        settings_snapshot=_loads(row["settings_snapshot"]), launch_id=row["launch_id"],
        error=_loads(row["error"]), usage=_loads(row["usage"]),
        context_stats=_loads(row["context_stats"]), last_seq=row["last_seq"],
        started_at=row["started_at"], finished_at=row["finished_at"],
    )


def _event(row: sqlite3.Row) -> Event:
    return Event(
        run_id=row["run_id"], seq=row["seq"], ts=row["ts"],
        type=row["type"], payload=_loads(row["payload"]),
    )


def _step(row: sqlite3.Row) -> Step:
    return Step(
        id=row["id"], node_id=row["node_id"], idx=row["idx"], kind=row["kind"],
        content=_loads(row["content"]), call_id=row["call_id"],
        is_error=bool(row["is_error"]), status=row["status"],
        tokens=row["tokens"], object_id=row["object_id"],
    )


def _object(row: sqlite3.Row) -> CatalogObject:
    return CatalogObject(
        id=row["id"], chat_id=row["chat_id"], run_id=row["run_id"],
        step_id=row["step_id"], node_id=row["node_id"], name=row["name"],
        kind=row["kind"], store=row["store"], schema=_loads(row["schema"]),
        row_count=row["row_count"], tokens=row["tokens"],
        provenance=_loads(row["provenance"]), created_at=row["created_at"],
    )


# ---------------------------------------------------------------- repository --


class Repo:
    """All persistence for Atlas' app state."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # --------------------------------------------------------------- chats --

    def create_chat(self, title: str | None = None) -> Chat:
        """Create a chat with its synthetic root node, atomically.

        ``chats.root_id`` and ``nodes.chat_id`` reference each other, so one of
        them has to be filled in a second statement. Both happen inside the same
        transaction, so the half-linked pair is never observable.
        """
        ts = now_ms()
        chat_id, root_id = new_ulid(), new_ulid()
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO chats (id, title, root_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?)",
                (chat_id, title, None, ts, ts),
            )
            conn.execute(
                "INSERT INTO nodes (id, chat_id, parent_id, role, content,"
                " selected_child_id, created_at) VALUES (?,?,?,?,?,?,?)",
                (root_id, chat_id, None, "root", None, None, ts),
            )
            conn.execute("UPDATE chats SET root_id=? WHERE id=?", (root_id, chat_id))
        return Chat(chat_id, title, root_id, ts, ts, None)

    def get_chat(self, chat_id: str) -> Chat:
        row = self.db.connection.execute(
            "SELECT * FROM chats WHERE id=?", (chat_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"chat {chat_id} not found")
        return _chat(row)

    def list_chats(self, include_deleted: bool = False) -> list[Chat]:
        sql = "SELECT * FROM chats"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY updated_at DESC"
        return [_chat(r) for r in self.db.connection.execute(sql)]

    def touch_chat(self, chat_id: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE chats SET updated_at=? WHERE id=?", (now_ms(), chat_id)
            )

    def rename_chat(self, chat_id: str, title: str) -> Chat:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE chats SET title=?, updated_at=? WHERE id=?",
                (title, now_ms(), chat_id),
            )
        return self.get_chat(chat_id)

    # --------------------------------------------------------------- nodes --

    def get_node(self, node_id: str) -> Node:
        row = self.db.connection.execute(
            "SELECT * FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"node {node_id} not found")
        return _node(row)

    def children(self, node_id: str) -> list[Node]:
        """Direct children, in creation order (the sibling order for the UI)."""
        rows = self.db.connection.execute(
            "SELECT * FROM nodes WHERE parent_id=? ORDER BY created_at, id", (node_id,)
        )
        return [_node(r) for r in rows]

    def visible_path(self, chat_id: str) -> list[Node]:
        """root -> ... -> leaf, following ``selected_child_id`` (section 5)."""
        chat = self.get_chat(chat_id)
        path: list[Node] = []
        seen: set[str] = set()
        current: str | None = chat.root_id

        while current:
            if current in seen:
                raise BadRequest(
                    f"cycle in selected_child_id at node {current}",
                    chat_id=chat_id,
                )
            seen.add(current)
            node = self.get_node(current)
            path.append(node)
            current = node.selected_child_id

        return path

    def visible_leaf(self, chat_id: str) -> Node:
        path = self.visible_path(chat_id)
        return path[-1]

    def visible_path_to(self, node_id: str) -> list[Node]:
        """The visible path truncated at ``node_id``, inclusive.

        What a run needs: the conversation up to and including the user node it
        answers. The run's own assistant node sits at the end of the full path
        but has no steps yet, so slicing is clearer than relying on it being empty.
        """
        node = self.get_node(node_id)
        path = self.visible_path(node.chat_id)
        for index, candidate in enumerate(path):
            if candidate.id == node_id:
                return path[: index + 1]
        raise NotFound(f"node {node_id} is not on the visible path")

    def tree_with_siblings(self, chat_id: str) -> list[TreeNode]:
        """The visible path annotated with siblings, for the `<` `>` switcher."""
        path = self.visible_path(chat_id)
        out: list[TreeNode] = []
        for node in path:
            siblings = (
                [node] if node.is_root else self.children(node.parent_id or node.id)
            )
            index = next((i for i, s in enumerate(siblings) if s.id == node.id), 0)
            out.append(TreeNode(node=node, siblings=siblings, sibling_index=index))
        return out

    def steps(self, node_id: str) -> list[Step]:
        rows = self.db.connection.execute(
            "SELECT * FROM steps WHERE node_id=? ORDER BY idx", (node_id,)
        )
        return [_step(r) for r in rows]

    def add_step(
        self,
        *,
        node_id: str,
        idx: int,
        kind: str,
        content: Any,
        status: str = "complete",
        call_id: str | None = None,
        is_error: bool = False,
        tokens: int = 0,
        object_id: str | None = None,
    ) -> Step:
        """Steps are written at step_finished, never for in-progress work."""
        step = Step(
            id=new_ulid(), node_id=node_id, idx=idx, kind=kind, content=content,
            call_id=call_id, is_error=is_error, status=status, tokens=tokens,
            object_id=object_id,
        )
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO steps (id, node_id, idx, kind, content, call_id,"
                " is_error, status, tokens, object_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (step.id, node_id, idx, kind, _dumps(content), call_id,
                 int(is_error), status, tokens, object_id, now_ms()),
            )
        return step

    # ---------------------------------------------------------------- runs --

    def active_run(self) -> Run | None:
        row = self.db.connection.execute(
            "SELECT * FROM runs WHERE status IN ('running','cancelling') LIMIT 1"
        ).fetchone()
        return _run(row) if row else None

    def get_run(self, run_id: str) -> Run:
        row = self.db.connection.execute(
            "SELECT * FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"run {run_id} not found")
        return _run(row)

    def runs_for_chat(self, chat_id: str) -> list[Run]:
        rows = self.db.connection.execute(
            "SELECT * FROM runs WHERE chat_id=? ORDER BY started_at", (chat_id,)
        )
        return [_run(r) for r in rows]

    def start_run(
        self,
        *,
        chat_id: str,
        text: str | None = None,
        attachment_ids: tuple[str, ...] = (),
        options: dict[str, Any] | None = None,
        settings_snapshot: dict[str, Any] | None = None,
        launch_id: str | None = None,
        origin: str = "send",
        edit_node_id: str | None = None,
        retry_node_id: str | None = None,
    ) -> Run:
        """The single guarded path for send / edit / retry (section 6).

        Creates whatever nodes the origin needs, then the run row. The whole
        thing is one transaction: if the global lock rejects the second
        concurrent start, nothing at all is written.
        """
        if origin not in ("send", "retry", "edit"):
            raise BadRequest(f"unknown origin {origin!r}")
        if origin != "send" and not (edit_node_id or retry_node_id):
            raise BadRequest(f"origin {origin!r} requires a node id")

        ts = now_ms()
        with self.db.write() as conn:
            self._require_no_active_run(conn)
            self._check_attachments_exist(conn, attachment_ids)

            if origin == "send":
                user_node = self._append_send(conn, chat_id, text, attachment_ids, ts)
            elif origin == "edit":
                user_node = self._append_edit(
                    conn, chat_id, edit_node_id, text, attachment_ids, ts
                )
            else:
                user_node = self._append_retry(conn, chat_id, retry_node_id, ts)

            assistant_node = self._insert_node(
                conn,
                chat_id=chat_id,
                parent_id=user_node.id,
                role="assistant",
                content=None,
                ts=ts,
            )
            self._select_child(conn, user_node.id, assistant_node.id)

            run_id = new_ulid()
            try:
                conn.execute(
                    "INSERT INTO runs (id, chat_id, user_node_id, assistant_node_id,"
                    " origin, status, options, settings_snapshot, launch_id,"
                    " last_seq, started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, chat_id, user_node.id, assistant_node.id, origin,
                     "running", _dumps(options), _dumps(settings_snapshot),
                     launch_id, 0, ts),
                )
            except sqlite3.IntegrityError as exc:
                # The partial unique index refused a second active run.
                if is_unique_violation(exc):
                    raise RunActive("a run is already in progress") from exc
                raise
            conn.execute(
                "UPDATE nodes SET run_id=? WHERE id=?", (run_id, assistant_node.id)
            )
            conn.execute("UPDATE chats SET updated_at=? WHERE id=?", (ts, chat_id))

        return self.get_run(run_id)

    # ---------------------------------------------------- tree construction --

    def _append_send(
        self,
        conn: sqlite3.Connection,
        chat_id: str,
        text: str | None,
        attachment_ids: tuple[str, ...],
        ts: int,
    ) -> Node:
        leaf = self._leaf_for_new_message(conn, chat_id)
        node = self._insert_node(
            conn,
            chat_id=chat_id,
            parent_id=leaf.id,
            role="user",
            content=self._user_content(text, attachment_ids),
            ts=ts,
        )
        self._link_attachments(conn, node.id, attachment_ids)
        self._select_child(conn, leaf.id, node.id)
        return node

    def _append_edit(
        self,
        conn: sqlite3.Connection,
        chat_id: str,
        edit_node_id: str | None,
        text: str | None,
        attachment_ids: tuple[str, ...],
        ts: int,
    ) -> Node:
        original = self._require_node(conn, edit_node_id)
        if original.role != "user":
            raise BadRequest(f"only user nodes can be edited, got {original.role}")
        if original.chat_id != chat_id:
            raise BadRequest("node belongs to a different chat")

        # Attachments are copied to the new sibling unless replaced.
        carried = attachment_ids or tuple(self._attachments_of(original.id))
        node = self._insert_node(
            conn,
            chat_id=chat_id,
            parent_id=original.parent_id,
            role="user",
            content=self._user_content(text, carried),
            ts=ts,
        )
        self._link_attachments(conn, node.id, carried)
        # The new node becomes the visible version of this position.
        self._select_child(conn, original.parent_id or original.id, node.id)
        return node

    def _append_retry(
        self, conn: sqlite3.Connection, chat_id: str, retry_node_id: str | None, ts: int
    ) -> Node:
        """Validate the retry target and return its user node.

        The new assistant node is deliberately *not* created here: ``start_run``
        creates it on the shared path, as a sibling of the original assistant
        (same parent), which is exactly what section 6 asks for. Creating one
        here as well would leave two assistant nodes per retry.
        """
        original = self._require_node(conn, retry_node_id)
        if original.role != "assistant":
            raise BadRequest(f"only assistant nodes can be retried, got {original.role}")
        if original.chat_id != chat_id:
            raise BadRequest("node belongs to a different chat")
        if not original.parent_id:
            raise BadRequest("cannot retry a node with no parent")

        return self._require_node(conn, original.parent_id)

    def select(self, node_id: str) -> Node:
        """Switch versions: update exactly one ``selected_child_id``."""
        node = self.get_node(node_id)
        if node.is_root:
            raise BadRequest("cannot select the root node")
        with self.db.write() as conn:
            self._select_child(conn, node.parent_id or "", node_id)
            conn.execute(
                "UPDATE chats SET updated_at=? WHERE id=?", (now_ms(), node.chat_id)
            )
        return self.get_node(node.id)

    # ------------------------------------------------------------- helpers --

    def _insert_node(
        self,
        conn: sqlite3.Connection,
        *,
        chat_id: str,
        parent_id: str | None,
        role: str,
        content: Any,
        ts: int,
    ) -> Node:
        node = Node(
            id=new_ulid(), chat_id=chat_id, parent_id=parent_id, role=role,
            content=content, run_id=None, selected_child_id=None,
            task_state=None, created_at=ts,
        )
        conn.execute(
            "INSERT INTO nodes (id, chat_id, parent_id, role, content,"
            " selected_child_id, created_at) VALUES (?,?,?,?,?,?,?)",
            (node.id, chat_id, parent_id, role, _dumps(content), None, ts),
        )
        return node

    def _select_child(self, conn: sqlite3.Connection, parent_id: str, child_id: str) -> None:
        if not parent_id:
            raise BadRequest("cannot select a child of the root node")
        conn.execute(
            "UPDATE nodes SET selected_child_id=? WHERE id=?", (child_id, parent_id)
        )

    def _require_node(self, conn: sqlite3.Connection, node_id: str | None) -> Node:
        if not node_id:
            raise BadRequest("missing node id")
        row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            raise NotFound(f"node {node_id} not found")
        return _node(row)

    def _require_no_active_run(self, conn: sqlite3.Connection) -> None:
        """Fail fast with 409 rather than waiting on the unique index.

        The index is still the real guarantee; this only produces a clearer
        error for the common case of a user pressing send twice.
        """
        row = conn.execute(
            "SELECT id FROM runs WHERE status IN ('running','cancelling') LIMIT 1"
        ).fetchone()
        if row is not None:
            raise RunActive(f"run {row['id']} is already in progress")

    def _leaf_for_new_message(self, conn: sqlite3.Connection, chat_id: str) -> Node:
        """The visible leaf, checked for acceptability (section 5)."""
        chat_row = conn.execute(
            "SELECT * FROM chats WHERE id=?", (chat_id,)
        ).fetchone()
        if chat_row is None:
            raise NotFound(f"chat {chat_id} not found")

        current: str | None = chat_row["root_id"]
        seen: set[str] = set()
        node = None
        while current:
            if current in seen:
                raise BadRequest("cycle in selected_child_id", chat_id=chat_id)
            seen.add(current)
            node = self._require_node(conn, current)
            current = node.selected_child_id

        assert node is not None
        if node.role == "root":
            return node

        if node.role == "assistant" and node.run_id:
            run = conn.execute(
                "SELECT status FROM runs WHERE id=?", (node.run_id,)
            ).fetchone()
            status = run["status"] if run else None
            if status in COMPLETABLE_STATUSES:
                return node
            raise ParentNotAccepting(
                f"the last assistant message ended as {status!r}; retry it "
                "instead of starting a new message",
                node_id=node.id,
                run_status=status,
            )

        raise ParentNotAccepting(
            f"cannot attach to a {node.role} node", node_id=node.id
        )

    def _check_attachments_exist(
        self, conn: sqlite3.Connection, attachment_ids: tuple[str, ...]
    ) -> None:
        """Only existence is enforced here; readiness is not.

        This used to raise ``AttachmentNotReady`` and the server turned that
        into a 422. Measured: that is the wrong place to put the wait, because
        it makes the *user* wait. A 57 KB xlsx takes ~1s to parse, so any send
        during that second was rejected -- the send button appears broken for
        reasons the user cannot see or influence. Worse, the frontend was not
        even sending the ids, so the gate never fired and the model simply
        answered with no idea the file existed: a silent wrong answer, which is
        far worse than a slow one.

        Readiness is now settled inside the run (``RunExecutor.settle``), after
        the message has been accepted and the event stream is open. The user
        never blocks; the model either gets the file or is told by name that it
        is not available yet.
        """
        for attachment_id in attachment_ids:
            row = conn.execute(
                "SELECT id FROM attachments WHERE id=?", (attachment_id,)
            ).fetchone()
            if row is None:
                raise NotFound(f"attachment {attachment_id} not found")

    def _user_content(self, text: str | None, attachment_ids: tuple[str, ...]) -> dict:
        blocks: list[dict] = []
        if text:
            blocks.append({"type": "text", "text": text})
        for attachment_id in attachment_ids:
            blocks.append({"type": "attachment", "attachment_id": attachment_id})
        return {"blocks": blocks}

    def _link_attachments(
        self, conn: sqlite3.Connection, node_id: str, attachment_ids: tuple[str, ...]
    ) -> None:
        for position, attachment_id in enumerate(attachment_ids):
            conn.execute(
                "INSERT OR REPLACE INTO node_attachments (node_id, attachment_id,"
                " position) VALUES (?,?,?)",
                (node_id, attachment_id, position),
            )

    def _attachments_of(self, node_id: str) -> list[str]:
        rows = self.db.connection.execute(
            "SELECT attachment_id FROM node_attachments WHERE node_id=?"
            " ORDER BY position",
            (node_id,),
        )
        return [r["attachment_id"] for r in rows]

    def attachments_of(self, node_id: str) -> list[str]:
        return self._attachments_of(node_id)

    def attachment_states(self, attachment_ids: tuple[str, ...] | list[str]) -> dict[str, dict[str, Any]]:
        """Latest extraction status per attachment, keyed by attachment id.

        Read outside any transaction: this is polled in a loop while the
        ingest worker writes, and holding the write lock between polls would
        serialise the two.
        """
        out: dict[str, dict[str, Any]] = {}
        if not attachment_ids:
            return out
        for attachment_id in attachment_ids:
            row = self.db.connection.execute(
                "SELECT id, handle, original_name FROM attachments WHERE id=?",
                (attachment_id,),
            ).fetchone()
            if row is None:
                continue
            status_row = self.db.connection.execute(
                "SELECT status, error, progress FROM attachment_extractions"
                " WHERE attachment_id=? ORDER BY created_at DESC LIMIT 1",
                (attachment_id,),
            ).fetchone()
            out[attachment_id] = {
                "id": row["id"],
                "handle": row["handle"],
                "name": row["original_name"],
                # No extraction row at all means it has not been queued yet,
                # which is indistinguishable from "queued" from here.
                "status": (status_row["status"] if status_row else "queued"),
                "error": (status_row["error"] if status_row else None),
                "progress": (status_row["progress"] if status_row else 0.0),
            }
        return out

    # ------------------------------------------------------------- events --

    def append_event(
        self, run_id: str, type: str, payload: Any = None, *, ts: int | None = None
    ) -> Event:
        """Append to the replay log with a gap-free, monotonic ``seq`` from 1.

        The sequence number is allocated by the database itself (an UPDATE ...
        RETURNING inside the same transaction as the INSERT), so concurrent
        appends cannot collide or leave a hole: if the INSERT fails, the
        increment rolls back with it.
        """
        ts = now_ms() if ts is None else ts
        with self.db.write() as conn:
            return self._insert_event(conn, run_id, type, payload, ts)

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        type: str,
        payload: Any,
        ts: int,
    ) -> Event:
        row = conn.execute(
            "UPDATE runs SET last_seq = last_seq + 1 WHERE id=? RETURNING last_seq",
            (run_id,),
        ).fetchone()
        if row is None:
            raise NotFound(f"run {run_id} not found")
        seq = int(row["last_seq"])

        try:
            conn.execute(
                "INSERT INTO run_events (run_id, seq, ts, type, payload)"
                " VALUES (?,?,?,?,?)",
                (run_id, seq, ts, type, _dumps(payload) or "{}"),
            )
        except sqlite3.IntegrityError as exc:
            if type in TERMINAL_EVENT_TYPES:
                raise TerminalEventExists(
                    f"run {run_id} already has a terminal event", run_id=run_id
                ) from exc
            raise

        return Event(run_id=run_id, seq=seq, ts=ts, type=type, payload=payload)

    def events(self, run_id: str, after: int = 0, limit: int | None = None) -> list[Event]:
        """Replay from ``after`` (SSE ``id`` = ``seq``, section 8)."""
        sql = "SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq"
        params: list[Any] = [run_id, after]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_event(r) for r in self.db.connection.execute(sql, params)]

    # -------------------------------------------------------- finalisation --

    def finalize_run(
        self,
        run_id: str,
        *,
        status: str,
        event_type: str | None = None,
        payload: Any = None,
        usage: Any = None,
        context_stats: Any = None,
        error: Any = None,
        task_state: Any = None,
        ts: int | None = None,
    ) -> Event:
        """Terminal event, run status and node finalisation, in ONE transaction.

        Section 8 rule 1: a client that reconnects after seeing the terminal
        event must never see a run that is still marked running, or a node
        without its compacted task state.
        """
        if event_type is None:
            event_type = f"run_{status}"
        if event_type not in TERMINAL_EVENT_TYPES:
            raise BadRequest(
                f"{event_type!r} is not a terminal event type",
                allowed=list(TERMINAL_EVENT_TYPES),
            )
        ts = now_ms() if ts is None else ts

        with self.db.write() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise NotFound(f"run {run_id} not found")
            run = _run(row)
            if not run.is_active:
                raise RunFinished(
                    f"run {run_id} already finished as {run.status!r}",
                    run_id=run_id, status=run.status,
                )

            event = self._insert_event(conn, run_id, event_type, payload, ts)

            conn.execute(
                "UPDATE runs SET status=?, finished_at=?, usage=?, context_stats=?,"
                " error=? WHERE id=?",
                (status, ts, _dumps(usage), _dumps(context_stats),
                 _dumps(error), run_id),
            )
            if run.assistant_node_id:
                conn.execute(
                    "UPDATE nodes SET task_state=? WHERE id=?",
                    (_dumps(task_state), run.assistant_node_id),
                )
        return event

    def request_cancel(self, run_id: str) -> Run:
        """API-side cancel: mark ``cancelling`` and let the executor wind down."""
        with self.db.write() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise NotFound(f"run {run_id} not found")
            run = _run(row)
            if not run.is_active:
                raise RunFinished(
                    f"run {run_id} is {run.status}", run_id=run_id, status=run.status
                )
            conn.execute("UPDATE runs SET status='cancelling' WHERE id=?", (run_id,))
        return self.get_run(run_id)

    def recover_interrupted(self, *, ts: int | None = None) -> list[str]:
        """Startup recovery (sections 7 and 9).

        A run still marked active cannot have a live executor: the backend just
        started. Mark them ``interrupted`` and emit the terminal event so the
        partial output is replayable and the global lock is released.
        """
        ts = now_ms() if ts is None else ts
        recovered: list[str] = []
        with self.db.write() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE status IN ('running','cancelling')"
            ).fetchall()
            for row in rows:
                run = _run(row)
                payload = {
                    "error": {
                        "code": "interrupted",
                        "message": "backend restarted while this run was active",
                        "retryable": True,
                    },
                    "phase": "startup_recovery",
                }
                try:
                    self._insert_event(conn, run.id, "run_failed", payload, ts)
                except TerminalEventExists:
                    pass
                conn.execute(
                    "UPDATE runs SET status='interrupted', finished_at=?, error=?"
                    " WHERE id=?",
                    (ts, _dumps(payload["error"]), run.id),
                )
                recovered.append(run.id)
        return recovered

    # ------------------------------------------------------------ catalog --

    def add_object(
        self,
        *,
        chat_id: str,
        name: str,
        kind: str,
        store: str,
        run_id: str | None = None,
        step_id: str | None = None,
        node_id: str | None = None,
        schema: Any = None,
        row_count: int | None = None,
        tokens: int | None = None,
        provenance: Any = None,
    ) -> CatalogObject:
        """Register an immutable object. L2 registers; L5 resolves with lineage."""
        obj = CatalogObject(
            id=new_ulid(), chat_id=chat_id, run_id=run_id, step_id=step_id,
            node_id=node_id, name=name, kind=kind, store=store, schema=schema,
            row_count=row_count, tokens=tokens, provenance=provenance,
            created_at=now_ms(),
        )
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO catalog_objects (id, chat_id, run_id, step_id, node_id,"
                " name, kind, store, schema, row_count, tokens, provenance, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (obj.id, chat_id, run_id, step_id, node_id, name, kind, store,
                 _dumps(schema), row_count, tokens, _dumps(provenance),
                 obj.created_at),
            )
        return obj

    def objects(self, chat_id: str) -> list[CatalogObject]:
        rows = self.db.connection.execute(
            "SELECT * FROM catalog_objects WHERE chat_id=? ORDER BY created_at",
            (chat_id,),
        )
        return [_object(r) for r in rows]


__all__ = [
    "ACTIVE_STATUSES",
    "TERMINAL_EVENT_TYPES",
    "CatalogObject",
    "Chat",
    "Event",
    "Node",
    "Repo",
    "Run",
    "Step",
    "TreeNode",
]
