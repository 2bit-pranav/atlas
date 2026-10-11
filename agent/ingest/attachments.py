"""Attachment, extraction and chunk persistence (spec sections 12 and 11.4).

This is the SQLite half of ingestion. The routing rule of section 11.3 decides
what lands here without anyone inspecting content: outlines, chunks and the
keyword index are text, so they go to SQLite; tables go to DuckDB. An ambiguous
table is stored in *both* -- as a DuckDB table for SQL, and as ``table_text``
chunks so keyword search can find it.

Two behaviours worth calling out:

* **Uploads are deduplicated by sha256** (section 12). Re-uploading the same
  file returns the existing handle instead of ingesting it twice.
* **The cache key is the content, not the path** --
  (sha256, parser, parser_version, pipeline, embed_model). Retries and
  re-uploads never re-parse.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.core.db import Database
from agent.core.errors import BadRequest, NotFound
from agent.core.repo import Repo
from agent.ids import new_ulid, now_ms
from agent.ingest.contract import Chunk, IngestResult, TableSpec


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _same_name(left: str | None, right: str | None) -> bool:
    """Filenames compare case-insensitively, the way the filesystem does."""
    return (left or "").strip().casefold() == (right or "").strip().casefold()


class AttachmentStore:
    """Everything ingestion needs to persist, over the existing L2 database."""

    def __init__(self, db: Database, repo: Repo | None = None) -> None:
        self.db = db
        self.repo = repo or Repo(db)

    # ----------------------------------------------------------- attachments --

    def next_handle(self) -> str:
        """The next ``f1``, ``f2`` ... handle (spec section 11.1)."""
        row = self.db.connection.execute(
            "SELECT handle FROM attachments ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return "f1"
        digits = "".join(c for c in str(row["handle"]) if c.isdigit())
        return f"f{int(digits) + 1}" if digits else "f1"

    def create_attachment(
        self,
        *,
        sha256: str,
        original_name: str,
        mime: str | None,
        size: int,
        storage_path: str,
    ) -> tuple[dict[str, Any], bool]:
        """Register an upload. Returns ``(attachment, deduped)``.

        Deduplicated by sha256, globally: the same bytes keep the same handle
        and the same parse, whichever chat uploaded them. That is the point --
        the bytes live in ``blobs/<sha256>`` and the parsed tables in one shared
        DuckDB, both addressed by handle, so a second chat reuses the first
        chat's work instead of starting over.

        A chat's view of a file comes from ``attachment_uploads`` /
        ``node_attachments``, not from the attachment row, which is what lets
        one attachment belong to many chats.

        When the bytes match but the *name* does not, the name is kept as an
        alias rather than dropped or overwriting the original. Uploading
        ``resume.pdf`` and later ``resume_new.pdf`` gives one file with one
        handle that answers to both.
        """
        existing = self.db.connection.execute(
            "SELECT * FROM attachments WHERE sha256=?", (sha256,)
        ).fetchone()
        if existing is not None:
            attachment = dict(existing)
            if original_name and not _same_name(
                attachment["original_name"], original_name
            ):
                self.add_alias(attachment["id"], original_name)
            return attachment, True

        attachment_id = new_ulid()
        handle = self.next_handle()
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO attachments (id, sha256, handle, original_name, mime,"
                " size, storage_path, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (attachment_id, sha256, handle, original_name, mime, size,
                 storage_path, now_ms()),
            )
        row = self.db.connection.execute(
            "SELECT * FROM attachments WHERE id=?", (attachment_id,)
        ).fetchone()
        return dict(row), False

    # ------------------------------------------------------------- aliases --

    def add_alias(self, attachment_id: str, name: str) -> None:
        """Record another name this same content has been uploaded under."""
        with self.db.write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO attachment_aliases"
                " (attachment_id, name, created_at) VALUES (?,?,?)",
                (attachment_id, name, now_ms()),
            )

    def aliases(self, attachment_id: str) -> list[str]:
        """Every name besides the canonical one, oldest first."""
        rows = self.db.connection.execute(
            "SELECT name FROM attachment_aliases WHERE attachment_id=?"
            " ORDER BY created_at, name",
            (attachment_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    def all_names(self, attachment_id: str) -> list[str]:
        """Canonical name first, then aliases. What a handle answers to."""
        row = self.db.connection.execute(
            "SELECT original_name FROM attachments WHERE id=?", (attachment_id,)
        ).fetchone()
        if row is None:
            return []
        return [row["original_name"], *self.aliases(attachment_id)]

    def attachment(self, attachment_id: str) -> dict[str, Any]:
        row = self.db.connection.execute(
            "SELECT * FROM attachments WHERE id=?", (attachment_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"attachment {attachment_id} not found")
        return dict(row)

    def attachment_by_handle(self, handle: str) -> dict[str, Any]:
        row = self.db.connection.execute(
            "SELECT * FROM attachments WHERE handle=?", (handle,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no attachment with handle {handle!r}")
        return dict(row)

    def note_upload(self, attachment_id: str, chat_id: str) -> None:
        """Record that this file was added to this chat, message or not."""
        with self.db.write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO attachment_uploads (attachment_id, chat_id,"
                " created_at) VALUES (?,?,?)",
                (attachment_id, chat_id, now_ms()),
            )

    def attachments_for_chat(self, chat_id: str) -> list[dict[str, Any]]:
        """Files added to this chat: uploaded here, or attached to a message.

        The two sources are unioned because ``node_attachments`` only gains a
        row once a message references the file, and a file uploaded a moment
        earlier is still the user's to see.
        """
        rows = self.db.connection.execute(
            """
            SELECT a.* FROM attachments a
            WHERE a.id IN (SELECT attachment_id FROM attachment_uploads WHERE chat_id = ?)
               OR a.id IN (
                    SELECT na.attachment_id FROM node_attachments na
                    JOIN nodes n ON n.id = na.node_id
                    WHERE n.chat_id = ?
               )
            ORDER BY a.rowid
            """,
            (chat_id, chat_id),
        )
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- extractions --

    def create_extraction(
        self, attachment_id: str, parser: str, parser_version: str,
        docling_pipeline: str | None = None,
    ) -> dict[str, Any]:
        """Create the extraction row, or return the cached one (section 12)."""
        existing = self.db.connection.execute(
            "SELECT * FROM attachment_extractions"
            " WHERE attachment_id=? AND parser=? AND parser_version=?"
            " AND docling_pipeline IS ?",
            (attachment_id, parser, parser_version, docling_pipeline),
        ).fetchone()
        if existing is not None:
            return dict(existing)

        extraction_id = new_ulid()
        ts = now_ms()
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO attachment_extractions (id, attachment_id, parser,"
                " parser_version, docling_pipeline, status, progress, embed_status,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (extraction_id, attachment_id, parser, parser_version,
                 docling_pipeline, "queued", 0.0, "none", ts, ts),
            )
        return self.extraction(extraction_id)

    def extraction(self, extraction_id: str) -> dict[str, Any]:
        row = self.db.connection.execute(
            "SELECT * FROM attachment_extractions WHERE id=?", (extraction_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"extraction {extraction_id} not found")
        return dict(row)

    def latest_extraction(self, attachment_id: str) -> dict[str, Any] | None:
        row = self.db.connection.execute(
            "SELECT * FROM attachment_extractions WHERE attachment_id=?"
            " ORDER BY rowid DESC LIMIT 1",
            (attachment_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_extraction(self, extraction_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status", "progress", "embed_status", "embed_model", "outline",
            "table_ids", "warnings", "token_count", "page_count", "doc_json_path",
            "error",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise BadRequest(f"cannot update extraction fields: {sorted(unknown)}")
        columns = ", ".join(f"{k}=?" for k in fields)
        values = [
            _dumps(v) if k in ("outline", "table_ids", "warnings") else v
            for k, v in fields.items()
        ]
        values.append(now_ms())
        values.append(extraction_id)
        with self.db.write() as conn:
            conn.execute(
                f"UPDATE attachment_extractions SET {columns}, updated_at=?"
                " WHERE id=?",
                values,
            )

    # ---------------------------------------------------------------- chunks --

    def replace_chunks(
        self, attachment_id: str, extraction_id: str, chunks: list[Chunk]
    ) -> int:
        """Write chunks for an extraction, replacing any previous attempt."""
        ts = now_ms()
        rows = [
            chunk.to_row(new_ulid(), attachment_id, extraction_id, ts)
            for chunk in chunks
        ]
        with self.db.write() as conn:
            conn.execute(
                "DELETE FROM chunks WHERE extraction_id=?", (extraction_id,)
            )
            conn.executemany(
                "INSERT INTO chunks (id, attachment_id, extraction_id, scope, idx,"
                " kind, section_path, location, text, tokens, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    def chunks(
        self, attachment_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM chunks"
        params: list[Any] = []
        if attachment_id:
            sql += " WHERE attachment_id=?"
            params.append(attachment_id)
        sql += " ORDER BY attachment_id, idx"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in self.db.connection.execute(sql, params)]

    def search_chunks(
        self,
        query: str,
        *,
        attachment_ids: list[str] | None = None,
        kind: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Keyword search over the FTS5 index (section 11.4).

        Snippets are truncated to ~80 tokens, which is the display budget the
        spec sets for a search hit -- the model can ``read`` around it.
        Vector fusion arrives in L4d.
        """
        sql = [
            "SELECT c.id, c.attachment_id, c.section_path, c.location, c.kind,",
            "       snippet(chunks_fts, 0, '', '', '...', 24) AS snippet,",
            "       bm25(chunks_fts) AS score",
            "FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid",
            "WHERE chunks_fts MATCH ?",
        ]
        params: list[Any] = [_fts_query(query)]
        if attachment_ids:
            sql.append(f"AND c.attachment_id IN ({','.join('?' * len(attachment_ids))})")
            params.extend(attachment_ids)
        if kind:
            sql.append("AND c.kind = ?")
            params.append(kind)
        sql.append("ORDER BY score LIMIT ?")
        params.append(limit)

        try:
            rows = self.db.connection.execute(" ".join(sql), params).fetchall()
        except sqlite3.OperationalError:
            # A malformed MATCH expression is a user error, not a crash.
            return []
        return [dict(r) for r in rows]

    def rebuild_fts(self) -> int:
        """Rebuild the index; also the recovery step if it ever drifts."""
        with self.db.write() as conn:
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
            row = conn.execute("SELECT count(*) FROM chunks").fetchone()
        return int(row[0])

    # --------------------------------------------------------------- status --

    def status(self, attachment_id: str) -> dict[str, Any]:
        """What ``GET /attachments/{id}`` reports (section 14)."""
        attachment = self.attachment(attachment_id)
        extraction = self.latest_extraction(attachment_id)
        return {
            "id": attachment["id"],
            "handle": attachment["handle"],
            "original_name": attachment["original_name"],
            # Names this same content has also been uploaded under, so the UI
            # and the agent can both connect "resume_new.pdf" to this handle.
            "aliases": self.aliases(attachment["id"]),
            "mime": attachment["mime"],
            "size": attachment["size"],
            "status": (extraction or {}).get("status", "queued"),
            "progress": (extraction or {}).get("progress", 0.0),
            "embed_status": (extraction or {}).get("embed_status", "none"),
            "token_count": (extraction or {}).get("token_count"),
            "page_count": (extraction or {}).get("page_count"),
            "outline": json.loads((extraction or {}).get("outline") or "null"),
            "warnings": json.loads((extraction or {}).get("warnings") or "[]"),
            "error": (extraction or {}).get("error"),
        }


def _fts_query(query: str) -> str:
    """Turn a user phrase into a safe FTS5 MATCH expression.

    Bare user text can contain ``"``, ``*`` or ``NEAR``, any of which make
    FTS5 raise. Quoting every term keeps the query literal and predictable.
    """
    terms = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if t]
    if not terms:
        return '""'
    return " OR ".join(f'"{t}"' for t in terms)


__all__ = ["AttachmentStore"]
