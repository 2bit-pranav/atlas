"""Versioned schema migrations (spec section 5).

Migrations are numbered, applied in order, and each one runs inside a single
transaction together with the row that records it - so an interrupted upgrade
leaves the database on the last complete version rather than half-applied.

Sections are grouped by the layer that owns them. L2 owns chats, nodes, steps,
runs, run_events and the catalog; the attachment/text-index tables are declared
here too so the database is created whole, but their repositories arrive with L4.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

Migration = tuple[int, str, str]

#: (version, name, sql). Append only - never edit a shipped migration.
MIGRATIONS: list[Migration] = [
    (
        1,
        "initial",
        """
        -- chats ------------------------------------------------------------
        CREATE TABLE chats (
            id          TEXT PRIMARY KEY,
            title       TEXT,
            root_id     TEXT REFERENCES nodes(id),
            created_at  INTEGER NOT NULL,
            updated_at  INTEGER NOT NULL,
            deleted_at  INTEGER
        );

        -- nodes: the message tree ------------------------------------------
        -- A synthetic 'root' node per chat means editing the first message is
        -- an ordinary sibling operation (section 5).
        CREATE TABLE nodes (
            id                TEXT PRIMARY KEY,
            chat_id           TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            parent_id         TEXT REFERENCES nodes(id),
            role              TEXT NOT NULL CHECK (role IN ('root','user','assistant')),
            content           TEXT,                       -- user: JSON blocks
            run_id            TEXT UNIQUE REFERENCES runs(id),
            selected_child_id TEXT REFERENCES nodes(id),
            task_state        TEXT,                       -- assistant: JSON
            created_at        INTEGER NOT NULL
        );
        CREATE INDEX idx_nodes_chat ON nodes(chat_id);
        CREATE INDEX idx_nodes_parent ON nodes(parent_id, created_at);

        -- runs: one active run globally ------------------------------------
        CREATE TABLE runs (
            id                TEXT PRIMARY KEY,
            chat_id           TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            user_node_id      TEXT REFERENCES nodes(id),
            assistant_node_id TEXT REFERENCES nodes(id),
            origin            TEXT NOT NULL CHECK (origin IN ('send','retry','edit')),
            status            TEXT NOT NULL CHECK (status IN
                                ('running','cancelling','completed','failed',
                                 'cancelled','interrupted')),
            options           TEXT,
            settings_snapshot TEXT,
            launch_id         TEXT,
            error             TEXT,
            usage             TEXT,
            context_stats     TEXT,
            last_seq          INTEGER NOT NULL DEFAULT 0,
            started_at        INTEGER NOT NULL,
            finished_at       INTEGER
        );

        -- The global lock (section 5). A unique index over a constant
        -- expression, restricted to active statuses: the database itself
        -- refuses a second concurrent run, so no read-then-write race exists.
        CREATE UNIQUE INDEX idx_runs_single_active ON runs((1))
            WHERE status IN ('running','cancelling');
        CREATE INDEX idx_runs_chat ON runs(chat_id, started_at);

        -- run_events: append-only replay log (section 8) --------------------
        CREATE TABLE run_events (
            run_id  TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            seq     INTEGER NOT NULL,
            ts      INTEGER NOT NULL,
            type    TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (run_id, seq)
        );
        -- "Exactly one terminal event per run", enforced rather than assumed.
        CREATE UNIQUE INDEX idx_run_events_one_terminal ON run_events(run_id)
            WHERE type IN ('run_completed','run_failed','run_cancelled');

        -- steps: written at step_finished (section 5) -----------------------
        CREATE TABLE steps (
            id       TEXT PRIMARY KEY,
            node_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            idx      INTEGER NOT NULL,
            kind     TEXT NOT NULL CHECK (kind IN
                     ('thinking','text','tool_call','tool_result')),
            content  TEXT NOT NULL,
            call_id  TEXT,
            is_error INTEGER NOT NULL DEFAULT 0,
            status   TEXT NOT NULL CHECK (status IN ('complete','partial')),
            tokens   INTEGER NOT NULL DEFAULT 0,
            object_id TEXT,
            created_at INTEGER NOT NULL,
            UNIQUE (node_id, idx)
        );
        CREATE INDEX idx_steps_node ON steps(node_id, idx);

        -- catalog_objects (section 5, stub for L2) --------------------------
        CREATE TABLE catalog_objects (
            id         TEXT PRIMARY KEY,
            chat_id    TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            run_id     TEXT REFERENCES runs(id),
            step_id    TEXT REFERENCES steps(id),
            node_id    TEXT REFERENCES nodes(id),
            name       TEXT NOT NULL,
            kind       TEXT NOT NULL CHECK (kind IN
                         ('table','text','file','draft','image')),
            store      TEXT NOT NULL CHECK (store IN ('duckdb','sqlite','disk')),
            schema     TEXT,
            row_count  INTEGER,
            tokens     INTEGER,
            provenance TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX idx_catalog_chat ON catalog_objects(chat_id, created_at);
        """,
    ),
    (
        2,
        "attachments",
        """
        -- attachments (section 12); repositories arrive with L4 ------------
        --
        -- Identity is the file's content, not the chat it was uploaded to.
        -- Handles are allocated globally (`next_handle` counts every
        -- attachment), so a handle names one document in the whole
        -- installation, and a chat sees a file by virtue of a row in
        -- attachment_uploads or node_attachments. That is what lets the same
        -- bytes uploaded to a second chat reuse the first chat's parse
        -- instead of redoing it -- see `blobs/` and the shared DuckDB in
        -- atlas/core/paths.py.
        CREATE TABLE attachments (
            id            TEXT PRIMARY KEY,
            sha256        TEXT NOT NULL UNIQUE,
            handle        TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            mime          TEXT,
            size          INTEGER,
            storage_path  TEXT,
            created_at    INTEGER NOT NULL
        );

        CREATE TABLE node_attachments (
            node_id       TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            position      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (node_id, attachment_id)
        );

        CREATE TABLE attachment_extractions (
            id                TEXT PRIMARY KEY,
            attachment_id     TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            parser            TEXT NOT NULL CHECK (parser IN ('docling','tabular','text')),
            parser_version    TEXT NOT NULL,
            docling_pipeline  TEXT CHECK (docling_pipeline IN ('standard','vlm') OR docling_pipeline IS NULL),
            status            TEXT NOT NULL CHECK (status IN ('queued','running','ready','failed')),
            progress          REAL NOT NULL DEFAULT 0,
            embed_status      TEXT NOT NULL DEFAULT 'none' CHECK (embed_status IN
                                ('none','pending','ready','failed')),
            embed_model       TEXT,
            outline           TEXT,
            table_ids         TEXT,
            warnings          TEXT,
            token_count       INTEGER,
            page_count        INTEGER,
            doc_json_path     TEXT,
            error             TEXT,
            created_at        INTEGER NOT NULL,
            updated_at        INTEGER NOT NULL,
            UNIQUE (attachment_id, parser, parser_version, docling_pipeline)
        );
        CREATE INDEX idx_extraction_attachment ON attachment_extractions(attachment_id);
        """,
    ),
    (
        3,
        "chunks_and_fts",
        """
        -- chunks: the retrieval index over prose (section 11.4) ------------
        CREATE TABLE chunks (
            id            TEXT PRIMARY KEY,
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            extraction_id TEXT NOT NULL REFERENCES attachment_extractions(id) ON DELETE CASCADE,
            scope         TEXT NOT NULL DEFAULT 'chat' CHECK (scope IN ('chat','library')),
            idx           INTEGER NOT NULL,
            kind          TEXT NOT NULL CHECK (kind IN
                            ('text','table_text','schema','caption')),
            section_path  TEXT,
            location      TEXT,          -- JSON: page, heading path
            text          TEXT NOT NULL,
            tokens        INTEGER NOT NULL DEFAULT 0,
            created_at    INTEGER NOT NULL,
            UNIQUE (extraction_id, idx)
        );
        CREATE INDEX idx_chunks_attachment ON chunks(attachment_id, idx);
        CREATE INDEX idx_chunks_scope ON chunks(scope);

        -- Keyword index. Maintained by triggers so it can never drift from
        -- `chunks`, which matters because it is what `search` reads.
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            text, section_path, content='chunks', content_rowid='rowid'
        );
        CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, text, section_path)
            VALUES (new.rowid, new.text, new.section_path);
        END;
        CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text, section_path)
            VALUES ('delete', old.rowid, old.text, old.section_path);
        END;
        CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text, section_path)
            VALUES ('delete', old.rowid, old.text, old.section_path);
            INSERT INTO chunks_fts(rowid, text, section_path)
            VALUES (new.rowid, new.text, new.section_path);
        END;

        -- Lazy summaries (section 12); filled by L6.
        CREATE TABLE attachment_summaries (
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            section_path  TEXT,          -- NULL = whole document
            text          TEXT NOT NULL,
            tokens        INTEGER NOT NULL DEFAULT 0,
            model_id      TEXT,
            created_at    INTEGER NOT NULL,
            PRIMARY KEY (attachment_id, section_path)
        );
        """,
    ),
    (
        4,
        "attachment_uploads",
        """
        -- Which chat a file was added to, recorded at upload time.
        -- `node_attachments` only gains a row once a *message* references the
        -- file, so without this a freshly uploaded file is invisible in the UI
        -- until the first send.
        CREATE TABLE IF NOT EXISTS attachment_uploads (
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            chat_id        TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            created_at     INTEGER NOT NULL,
            PRIMARY KEY (attachment_id, chat_id)
        );
        CREATE INDEX IF NOT EXISTS idx_uploads_chat ON attachment_uploads(chat_id);
        """,
    ),
    (
        5,
        "text_objects",
        """
        -- Bodies of text objects (tool results too large to show inline).
        -- Immutable: a derived object gets a new row, so every number has
        -- recorded lineage (section 5).
        CREATE TABLE IF NOT EXISTS text_objects (
            object_id TEXT PRIMARY KEY REFERENCES catalog_objects(id) ON DELETE CASCADE,
            body      TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS text_objects_fts USING fts5(
            body, content='text_objects', content_rowid='rowid'
        );
        CREATE TRIGGER IF NOT EXISTS text_objects_ai AFTER INSERT ON text_objects BEGIN
            INSERT INTO text_objects_fts(rowid, body) VALUES (new.rowid, new.body);
        END;
        CREATE TRIGGER IF NOT EXISTS text_objects_ad AFTER DELETE ON text_objects BEGIN
            INSERT INTO text_objects_fts(text_objects_fts, rowid, body)
            VALUES ('delete', old.rowid, old.body);
        END;
        """,
    ),
    (
        7,
        "attachment_aliases",
        """
        -- One file, many names.
        --
        -- Identity is the content hash, so resume.pdf and resume_new.pdf with
        -- identical bytes are one attachment and share one parse. But the name
        -- is how the *user* refers to it, and they just called it
        -- resume_new.pdf. Storing a single name meant the first one won
        -- forever: the file was listed as resume.pdf while the user was looking
        -- at resume_new.pdf, and the agent could not connect the two.
        --
        -- Overwriting original_name instead would only move the problem -- a
        -- chat from yesterday that said "resume.pdf" would then find the file
        -- labelled resume_new.pdf. So the first name stays canonical and every
        -- later name is kept as an alias. list_files shows them, and a handle
        -- resolves by any of them.
        CREATE TABLE attachment_aliases (
            attachment_id TEXT NOT NULL
                REFERENCES attachments(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            created_at    INTEGER NOT NULL,
            PRIMARY KEY (attachment_id, name)
        );
        CREATE INDEX idx_attachment_aliases_name ON attachment_aliases(name);
        """,
    ),
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def current_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_migrations"):
        return 0
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return int(row["v"] or 0)


def split_statements(script: str) -> list[str]:
    """Split a SQL script into complete statements.

    ``executescript`` cannot be used here because it issues an implicit COMMIT
    before running, which would drop the surrounding transaction and destroy the
    all-or-nothing guarantee. ``sqlite3.complete_statement`` understands quotes
    and comments, so accumulating lines until each one is complete is safe.
    """
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            stripped = buffer.strip()
            if stripped:
                statements.append(stripped)
            buffer = ""
    leftover = buffer.strip()
    if leftover:
        statements.append(leftover)
    return statements


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every pending migration. Returns the resulting version.

    Each migration's DDL and its bookkeeping row share one transaction, so a
    crash mid-upgrade leaves the previous version intact.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at INTEGER NOT NULL
        )
        """
    )

    version = current_version(conn)
    for number, name, sql in MIGRATIONS:
        if number <= version:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in split_statements(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?,?,?)",
                (number, name, _now()),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        version = number
    return version


def _now() -> int:
    from agent.ids import now_ms

    return now_ms()


def pending(conn: sqlite3.Connection) -> list[Migration]:
    version = current_version(conn)
    return [m for m in MIGRATIONS if m[0] > version]


__all__ = [
    "MIGRATIONS",
    "Migration",
    "current_version",
    "migrate",
    "pending",
    "split_statements",
]
