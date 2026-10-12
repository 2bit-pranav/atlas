"""Ingestion pipeline: upload -> queue -> ingest -> ready (spec section 12).

    upload -> hash and dedupe -> attachment row + extraction 'queued' -> handle
      -> single worker -> 'ready'

Two-stage readiness, exactly as section 12 requires:

* **stage 1** (outline, chunks, FTS, DuckDB tables) makes the file usable, and
  flips the attachment to ``ready``. This is what unblocks sending a message.
* **stage 2** (embeddings) continues in the background and only moves
  ``embed_status``. Search works without it.

The worker is a **process** pool of size 1 (section 3), not a thread, so Docling
in L4c cannot block the event loop. The queue lives in the database, not in
memory, so a restart does not lose work: rows left ``running`` are re-queued.

Ingestion is independent of the run lock, so a run and a parse can overlap.
"""

from __future__ import annotations

import logging
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from agent.core.db import Database
from agent.core.errors import NotFound
from agent.core import paths
from agent.core.paths import blob_path, chat_workspace
from agent.ids import now_ms
from agent.ingest.attachments import AttachmentStore
from agent.ingest.contract import IngestResult
from agent.ingest.duckstore import DuckStore, register_tables
from agent.ingest.registry import pick_ingestor
from agent.ingest.text import PARSER as TEXT_PARSER
from agent.ingest.text import PARSER_VERSION as TEXT_VERSION

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 1


def _read_worker_settings() -> dict[str, Any]:
    """Read the few settings the worker needs.

    The worker is a separate process, so it cannot inherit live objects.
    """
    import os

    from agent.cli.settings import SettingsError, load_settings

    path = Path(os.environ.get("ATLAS_SETTINGS", "settings.json"))
    try:
        return load_settings(path).model_dump(mode="json")
    except (SettingsError, OSError):
        return {}


def ingest_one(
    db_path: str,
    attachment_id: str,
    extraction_id: str,
    chat_id: str,
    duck_path: str,
) -> dict[str, Any]:
    """Do the actual work. Runs in the worker process; returns a summary.

    ``duck_path`` is passed in rather than resolved here. This runs in a spawned
    process that re-imports the parent's ``__main__``, so anything the parent
    set up at module level -- env vars, a temp directory -- can differ by the
    time the child runs. Both sides resolving the path independently is how every
    parsed table ends up in a database nothing reads.
    """
    store = AttachmentStore(Database(db_path))
    attachment = store.attachment(attachment_id)
    path = Path(attachment["storage_path"])
    handle = attachment["handle"]

    try:
        store.update_extraction(extraction_id, status="running", progress=0.05)
        ingestor = pick_ingestor(attachment["original_name"], attachment.get("mime"))
        # Settings travel in the call, not just the environment: the Docling
        # pipeline choice (standard / vlm / auto) is a setting, and the worker
        # is a separate process that cannot read the parent's live objects.
        # The TypeError fallback keeps third-party ingestors working unchanged.
        try:
            result = ingestor.ingest(path, handle, _read_worker_settings())
        except TypeError:
            result = ingestor.ingest(path, handle)

        # Tables -> the shared DuckDB. Text/outline -> SQLite. Declared, not
        # inferred. Table names carry the global handle, so one parse serves
        # every chat that has this file.
        table_ids: list[str] = []
        if result.tables:
            duck = DuckStore(path=duck_path)
            try:
                registered, warnings = register_tables(duck, result.tables, handle)
                table_ids = [t.name for t in registered]
                result.warnings.extend(warnings)
            finally:
                duck.close()

        if result.chunks:
            store.replace_chunks(attachment_id, extraction_id, result.chunks)

        store.update_extraction(
            extraction_id,
            status="ready",
            progress=1.0,
            outline=result.outline,
            warnings=result.warnings,
            table_ids=table_ids,
            token_count=result.token_count,
            page_count=result.page_count,
            doc_json_path=result.doc_json_path,
            error=None,
        )
        return {
            "ok": True,
            "parser": result.parser,
            "chunks": len(result.chunks),
            "tables": table_ids,
            "warnings": result.warnings,
        }
    except Exception as exc:  # noqa: BLE001 - a failed parse must be visible
        detail = f"{type(exc).__name__}: {exc}"
        logger.error("ingest failed for %s: %s\n%s", attachment_id, detail, traceback.format_exc())
        try:
            store.update_extraction(extraction_id, status="failed", error=detail)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "error": detail}
    finally:
        store.db.close()


def _worker_entry(payload: dict[str, Any]) -> dict[str, Any]:
    return ingest_one(**payload)


class IngestWorker:
    """A single background worker. Independent of the run lock (section 2)."""

    def __init__(
        self,
        db_path: Path,
        workspace_root: Path | None = None,
        *,
        workers: int = DEFAULT_QUEUE_SIZE,
        duck_path: Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        # Resolved once, here, and handed to every job. See ingest_one.
        self.duck_path = Path(duck_path) if duck_path else paths.duck_path()
        self._pool: ProcessPoolExecutor | None = None
        self._futures: list[Any] = []

    def start(self) -> None:
        if self._pool is None:
            # Size 1: Docling is memory-hungry and the spec wants one worker.
            self._pool = ProcessPoolExecutor(max_workers=1)

    def stop(self, wait: bool = False) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=not wait)
            self._pool = None

    def submit(self, attachment_id: str, extraction_id: str, chat_id: str) -> None:
        self.start()
        assert self._pool is not None
        future = self._pool.submit(
            _worker_entry,
            {
                "db_path": str(self.db_path),
                "attachment_id": attachment_id,
                "extraction_id": extraction_id,
                "chat_id": chat_id,
                "duck_path": str(self.duck_path),
            },
        )
        self._futures.append(future)
        self._forget_done()

    def _forget_done(self) -> None:
        self._futures = [f for f in self._futures if not f.done()]

    @property
    def pending(self) -> int:
        self._forget_done()
        return len(self._futures)

    def requeue_running(self) -> list[str]:
        """Startup recovery: extractions left ``running`` have no worker (section 12)."""
        db = Database(self.db_path)
        try:
            store = AttachmentStore(db)
            rows = db.connection.execute(
                "SELECT id, attachment_id FROM attachment_extractions"
                " WHERE status='running'"
            ).fetchall()
            recovered = []
            for row in rows:
                store.update_extraction(row["id"], status="queued", progress=0.0)
                recovered.append(row["id"])
            return recovered
        finally:
            db.close()


class IngestService:
    """Upload and retry, from the API's point of view."""

    def __init__(
        self,
        db: Database,
        worker: IngestWorker,
        *,
        workspace_root: Path | None = None,
    ) -> None:
        self.db = db
        self.worker = worker
        self.store = AttachmentStore(db)
        # Kept for per-chat working files (scratch, outputs). Parsed data does
        # not live here -- blobs/ and duckdb/ are global.
        self.workspace_root = Path(workspace_root or chat_workspace("").parent)

    # ------------------------------------------------------------- uploads --

    def upload(
        self, chat_id: str, filename: str, data: bytes, mime: str | None = None
    ) -> dict[str, Any]:
        """Store the bytes, register the attachment, queue the parse.

        Returns immediately with the handle and ``status=queued``; the caller
        polls ``GET /attachments/{id}`` (section 12).
        """
        import hashlib

        sha = hashlib.sha256(data).hexdigest().upper()

        # Bytes are addressed by content and stored once, under blobs/. They do
        # not belong to a chat: the same file uploaded to a second chat reuses
        # this exact copy, and its parsed tables come from the shared DuckDB.
        # Writing them into workspace/<chat_id>/uploads/ instead meant the second
        # chat's attachment row pointed at the *first* chat's directory.
        target = blob_path(sha, Path(filename).suffix)
        target.parent.mkdir(parents=True, exist_ok=True)

        attachment, deduped = self.store.create_attachment(
            sha256=sha, original_name=filename, mime=mime,
            size=len(data), storage_path=str(target),
        )
        storage = Path(attachment["storage_path"])
        if not storage.exists():
            storage.write_bytes(data)

        # Record the chat association now: node_attachments only gains a row
        # once a message references the file, and the UI must show a file the
        # user just dropped even before they send anything. This is the *only*
        # thing tying a file to a chat -- which is what lets many chats share it.
        self.store.note_upload(attachment["id"], chat_id)

        status = self.store.status(attachment["id"])
        if deduped and status["status"] == "ready":
            # Same bytes already ingested: nothing to do, and no re-parse. The
            # tables are already in the shared DuckDB under this handle.
            return {**status, "deduped": True}

        ingestor = pick_ingestor(filename, mime)
        extraction = self.store.create_extraction(
            attachment["id"], ingestor.name, ingestor.version
        )
        self.worker.submit(attachment["id"], extraction["id"], chat_id)
        return {
            **self.store.status(attachment["id"]),
            "deduped": deduped,
            "extraction_id": extraction["id"],
        }

    def retry(self, attachment_id: str, chat_id: str) -> dict[str, Any]:
        """Re-run a failed parse (section 14)."""
        attachment = self.store.attachment(attachment_id)
        ingestor = pick_ingestor(
            attachment["original_name"], attachment.get("mime")
        )
        extraction = self.store.create_extraction(
            attachment_id, ingestor.name, ingestor.version
        )
        self.worker.submit(attachment_id, extraction["id"], chat_id)
        return self.store.status(attachment_id)

    def status(self, attachment_id: str) -> dict[str, Any]:
        return self.store.status(attachment_id)

    def outline(self, handle: str) -> dict[str, Any]:
        """``outline(handle)`` -- structure without loading the content (11.2)."""
        attachment = self.store.attachment_by_handle(handle)
        extraction = self.store.latest_extraction(attachment["id"])
        if not extraction or extraction["status"] != "ready":
            raise NotFound(f"{handle} is not ready yet")
        import json

        return {
            "handle": handle,
            "outline": json.loads(extraction.get("outline") or "{}"),
            "token_count": extraction.get("token_count"),
            "page_count": extraction.get("page_count"),
            "tables": json.loads(extraction.get("table_ids") or "[]"),
            "warnings": json.loads(extraction.get("warnings") or "[]"),
        }

    def search(
        self, query: str, *, target: str = "all", limit: int = 5
    ) -> list[dict[str, Any]]:
        """``search(target, query)`` -- keyword only until L4d adds vectors."""
        if target in ("all", "*"):
            return self.store.search_chunks(query, limit=limit)
        if target.startswith("f"):
            attachment = self.store.attachment_by_handle(target)
            return self.store.search_chunks(
                query, attachment_ids=[attachment["id"]], limit=limit
            )
        return self.store.search_chunks(query, limit=limit)


__all__ = ["IngestService", "IngestWorker", "ingest_one"]
