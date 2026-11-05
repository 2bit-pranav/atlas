"""The ingest store: every attached document parsed once, in the background.

One SQLite database, `<data>/parsed/index.db`, plus extracted images under
`<data>/parsed/<sha>/`:

    files    one row per content hash: type, status, pages, outline, page status
    blocks   the ordered blocks (parse.py), with an FTS5 index for search
    paths    path + size + mtime -> hash, so a file is hashed once
    owners   which chat may read which entry

**Ingest is not reading.** Uploads and imports call `submit`, which returns at
once; one worker thread parses. The read tools only fetch, and wait briefly
for pages still in progress. A PDF is published in two steps: every page's
text layer first (`partial`), then OCR of scanned pages, pages a read asked
for first, each committed as it finishes. Every write is a transaction, so a
crash leaves whole pages; the next `submit` resumes where it stopped.

**Shared by content, owned per chat.** Two chats attaching the same file share
one entry, but a chat reaches an entry (its blocks, its images) only through
`owners`, written when that chat attaches or reads the file -- after the
tool policy's access check. Deleting a chat drops its ownership and every
entry nobody else owns.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent.ingest import parse

logger = logging.getLogger(__name__)

KINDS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx"}
#: Page status: done, or still to do.
DONE = {"text", "ocr", "blank", "failed"}
PENDING = {"scan", "pictures"}

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS files (
    sha TEXT PRIMARY KEY, name TEXT, kind TEXT, status TEXT, parser INTEGER,
    pages INTEGER, outline TEXT, page_status TEXT, info TEXT, error TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS paths (path TEXT PRIMARY KEY, size INTEGER, mtime REAL, sha TEXT);
CREATE TABLE IF NOT EXISTS owners (chat TEXT, sha TEXT, PRIMARY KEY (chat, sha));
CREATE TABLE IF NOT EXISTS blocks (
    sha TEXT, seq INTEGER, id TEXT, kind TEXT, page INTEGER, section TEXT, text TEXT, extra TEXT,
    PRIMARY KEY (sha, seq));
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(text, sha UNINDEXED, seq UNINDEXED);
"""


def kind_of(path: Path) -> str | None:
    return KINDS.get(path.suffix.lower())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(root / "index.db"), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.queue: deque[tuple[str, Path]] = deque()
        self.queued: set[str] = set()
        self.wanted: dict[str, set[int]] = {}
        self.worker: threading.Thread | None = None

    # -------------------------------------------------------------- lookups --

    def identify(self, path: Path) -> str:
        """The file's content hash, from the path cache when size and mtime match."""
        st = path.stat()
        key = str(path.resolve())
        with self.lock:
            row = self.db.execute("SELECT size, mtime, sha FROM paths WHERE path=?", (key,)).fetchone()
        if row and row["size"] == st.st_size and row["mtime"] == st.st_mtime:
            return row["sha"]
        sha = sha256(path)
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO paths VALUES (?,?,?,?)", (key, st.st_size, st.st_mtime, sha))
        return sha

    def entry(self, sha: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM files WHERE sha=?", (sha,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        for k in ("outline", "page_status", "info"):
            out[k] = json.loads(out[k] or "null")
        return out

    def own(self, chat: str, sha: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO owners VALUES (?,?)", (chat, sha))

    def owner_of(self, chat: str, prefix: str) -> str | None:
        """The full hash of an entry `chat` owns, from its 12-character prefix."""
        if not re.fullmatch(r"[0-9a-f]{12}", prefix):
            return None
        with self.lock:
            row = self.db.execute("SELECT sha FROM owners WHERE chat=? AND substr(sha, 1, 12)=?",
                                  (chat, prefix)).fetchone()
        return row["sha"] if row else None

    def asset(self, chat: str, ref: str) -> Path | None:
        """`asset:<sha12>/<file>` as a path, only for an entry the chat owns."""
        m = re.fullmatch(r"asset:([0-9a-f]{12})/([\w.-]+)", ref.strip())
        if not m or (sha := self.owner_of(chat, m[1])) is None:
            return None
        path = self.root / sha / m[2]
        return path if path.is_file() else None

    def blocks(self, sha: str, pages: list[int] | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM blocks WHERE sha=?", [sha]
        if pages:
            sql += f" AND page IN ({','.join('?' * len(pages))})"
            args += pages
        with self.lock:
            rows = self.db.execute(sql + " ORDER BY seq", args).fetchall()
        return [_block(r) for r in rows]

    def search(self, sha: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Blocks holding the query's words, best first (bm25). Words, not the
        phrase: any of them may match, more matches rank higher."""
        words = re.findall(r"\w+", query.lower())
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in dict.fromkeys(words))
        with self.lock:
            rows = self.db.execute(
                "SELECT b.* FROM fts JOIN blocks b ON b.sha=fts.sha AND b.seq=fts.seq "
                "WHERE fts MATCH ? AND fts.sha=? ORDER BY bm25(fts) LIMIT ?", (match, sha, limit)).fetchall()
        return [_block(r) for r in rows]

    def find_text(self, query: str, limit: int = 200) -> list[tuple[str, str]]:
        """(file path, text) for every ingested document holding any of the words,
        best block first. The caller keeps only paths it may search."""
        words = re.findall(r"\w+", query.lower())
        if not words:
            return []
        match = " OR ".join(f'"{w}"*' for w in dict.fromkeys(words))
        with self.lock:
            rows = self.db.execute(
                # bm25() only works with the FTS table on its own, hence the materialized step.
                "WITH hits AS MATERIALIZED (SELECT sha, seq, bm25(fts) AS r FROM fts WHERE fts MATCH ?) "
                "SELECT p.path, group_concat(b.text, ' ') FROM hits h JOIN blocks b ON b.sha=h.sha AND b.seq=h.seq "
                "JOIN paths p ON p.sha=h.sha GROUP BY p.path ORDER BY min(h.r) LIMIT ?",
                (match, limit)).fetchall()
        return [(r[0], r[1] or "") for r in rows]

    # --------------------------------------------------------------- ingest --

    def submit(self, path: Path, chat: str) -> str | None:
        """Make sure `path` is (being) ingested; returns its hash, or None for a
        type that is not ingested. Never parses on the caller's thread."""
        if kind_of(path) is None or not path.is_file():
            return None
        sha = self.identify(path)
        if chat:
            self.own(chat, sha)
        e = self.entry(sha)
        with self.lock:
            done = e is not None and e["parser"] == parse.PARSER and e["status"] in ("ready", "failed")
            if not done and sha not in self.queued:
                self.queued.add(sha)
                self.queue.append((sha, path))
                self._start()
                self.changed.notify_all()
        return sha

    def want(self, sha: str, pages: list[int]) -> None:
        """Pages a read is waiting for: OCR'd before the others."""
        with self.lock:
            self.wanted.setdefault(sha, set()).update(pages)

    def wait(self, sha: str, ready: Callable[[dict[str, Any]], bool], timeout: float) -> dict[str, Any] | None:
        """The entry once `ready(entry)` holds, or as it stands after `timeout` seconds."""
        end = time.monotonic() + timeout
        with self.changed:
            while True:
                e = self.entry(sha)
                if e is not None and (ready(e) or e["status"] == "failed"):
                    return e
                left = end - time.monotonic()
                if left <= 0:
                    return e
                self.changed.wait(min(left, 0.5))

    def forget_chat(self, chat: str) -> None:
        """A deleted chat: drop its ownership and every entry nobody else owns."""
        with self.lock:
            self.db.execute("DELETE FROM owners WHERE chat=?", (chat,))
            orphans = [r["sha"] for r in self.db.execute(
                "SELECT sha FROM files WHERE sha NOT IN (SELECT sha FROM owners)").fetchall()]
            for sha in orphans:
                if sha in self.queued:
                    continue  # being parsed for someone; the next deletion sweeps it
                self._drop(sha)
                self.db.execute("DELETE FROM paths WHERE sha=?", (sha,))
        for sha in orphans:
            if sha not in self.queued:
                shutil.rmtree(self.root / sha, ignore_errors=True)

    # --------------------------------------------------------------- worker --

    def _start(self) -> None:
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._run, name="atlas-ingest", daemon=True)
            self.worker.start()

    def _run(self) -> None:
        while True:
            with self.changed:
                while not self.queue:
                    self.changed.wait()
                sha, path = self.queue.popleft()
            try:
                self._ingest(sha, path)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the worker
                logger.exception("ingest of %s failed", path.name)
                # A row even for a file never parsed before, so a read says it failed
                # rather than "still being read" (an UPDATE alone changed nothing).
                with self.changed:
                    self._file(sha, path, kind_of(path) or "", "failed", None, None, None, None)
                    self.db.execute("UPDATE files SET error=? WHERE sha=?", (f"{type(exc).__name__}: {exc}", sha))
                    self.changed.notify_all()
            finally:
                with self.changed:
                    if not any(s == sha for s, _ in self.queue):  # not handed back to the queue
                        self.queued.discard(sha)
                        self.wanted.pop(sha, None)
                        # Its chats were deleted while it was being parsed: sweep it now.
                        if self.db.execute("SELECT 1 FROM owners WHERE sha=?", (sha,)).fetchone() is None:
                            self._drop(sha)
                            self.db.execute("DELETE FROM paths WHERE sha=?", (sha,))
                            shutil.rmtree(self.root / sha, ignore_errors=True)
                    self.changed.notify_all()

    def _ingest(self, sha: str, path: Path) -> None:
        kind = kind_of(path)
        e = self.entry(sha)
        fresh = e is None or e["parser"] != parse.PARSER
        assets = self.root / sha
        if fresh:
            shutil.rmtree(assets, ignore_errors=True)
        if kind == "pdf":
            self._pdf(sha, path, assets, None if fresh else e)
            return
        if not fresh and e["status"] == "ready":
            return
        if kind == "docx":
            blocks, outline = parse.docx_blocks(path, sha, assets)
            info: dict[str, Any] = {"tables": sum(b["kind"] == "table" for b in blocks)}
        else:
            blocks, sheets = parse.xlsx_blocks(path)
            outline, info = [], {"sheets": sheets}
        with self._tx():
            self._drop(sha)
            self._file(sha, path, kind, "ready", None, outline, None, info)
            self._insert(sha, [(i, b) for i, b in enumerate(blocks, 1)])

    def _pdf(self, sha: str, path: Path, assets: Path, e: dict[str, Any] | None) -> None:
        doc = parse.pdf_open(path)
        try:
            total = len(doc)
            budget = [parse.MAX_IMAGES]
            if e is None:  # the text pass: every page's text layer, in one transaction
                status: list[str] = []
                rows: list[tuple[int, dict[str, Any]]] = []
                for i in range(total):
                    s, blocks = parse.pdf_page(doc, i, sha, assets, budget)
                    status.append(s)
                    rows += [((i + 1) * 1000 + k, b) for k, b in enumerate(blocks, 1)]
                with self._tx():
                    self._drop(sha)
                    self._file(sha, path, "pdf", "partial", total, parse.pdf_outline(doc), status, {})
                    self._insert(sha, rows)
            else:
                status = e["page_status"]
                with self.lock:
                    budget[0] -= self.db.execute("SELECT COUNT(*) FROM blocks WHERE sha=? AND kind='image'",
                                                 (sha,)).fetchone()[0]
            while True:  # then each pending page, the ones a read waits for first
                with self.lock:
                    pending = [i for i, s in enumerate(status) if s in PENDING]
                    wanted = sorted(i for i in pending if i + 1 in self.wanted.get(sha, ()))
                    # A file still waiting for its text pass goes first: a text PDF must
                    # not wait for another file's OCR (it waited 20 s behind a scan).
                    yield_to = any(e is None or e["parser"] != parse.PARSER
                                   for e in (self.entry(s) for s, _ in self.queue))
                    if pending and yield_to and not wanted:
                        self.queue.append((sha, path))
                        self.queued.add(sha)
                        return
                if not pending:
                    break
                i = (wanted or pending)[0]
                old = [b for b in self.blocks(sha, [i + 1])]
                try:
                    status[i], blocks = parse.pdf_ocr(doc, i, status[i], sha, assets, budget, old)
                except Exception:  # noqa: BLE001 - one page must not fail the document
                    logger.exception("OCR of page %d of %s failed", i + 1, path.name)
                    status[i], blocks = "failed", old
                with self._tx():
                    self._drop(sha, page=i + 1)
                    self._insert(sha, [((i + 1) * 1000 + k, b) for k, b in enumerate(blocks, 1)])
                    self.db.execute("UPDATE files SET page_status=?, updated=? WHERE sha=?",
                                    (json.dumps(status), time.time(), sha))
            with self.changed:
                self.db.execute("UPDATE files SET status='ready', updated=? WHERE sha=?", (time.time(), sha))
                self.changed.notify_all()
        finally:
            doc.close()

    # ---------------------------------------------------------------- rows --

    @contextmanager
    def _tx(self) -> Iterator[None]:
        """One transaction, rolled back on any error; waiting readers are woken after."""
        with self.changed:
            self.db.execute("BEGIN")
            try:
                yield
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
            self.changed.notify_all()

    def _file(self, sha: str, path: Path, kind: str, status: str, pages: int | None,
              outline: Any, page_status: Any, info: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (sha, path.name, kind, status, parse.PARSER, pages, json.dumps(outline),
                         json.dumps(page_status), json.dumps(info), None, time.time()))

    def _insert(self, sha: str, rows: list[tuple[int, dict[str, Any]]]) -> None:
        core = ("id", "kind", "page", "section", "text")
        for seq, b in rows:
            extra = {k: v for k, v in b.items() if k not in core}
            self.db.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)",
                            (sha, seq, b["id"], b["kind"], b.get("page"), b.get("section"), b["text"],
                             json.dumps(extra) if extra else None))
            if b["kind"] != "image":
                self.db.execute("INSERT INTO fts VALUES (?,?,?)", (b["text"], sha, seq))

    def _drop(self, sha: str, page: int | None = None) -> None:
        if page is None:
            self.db.execute("DELETE FROM fts WHERE sha=?", (sha,))
            self.db.execute("DELETE FROM blocks WHERE sha=?", (sha,))
            self.db.execute("DELETE FROM files WHERE sha=?", (sha,))
        else:
            lo, hi = page * 1000, page * 1000 + 999
            self.db.execute("DELETE FROM fts WHERE sha=? AND seq BETWEEN ? AND ?", (sha, lo, hi))
            self.db.execute("DELETE FROM blocks WHERE sha=? AND seq BETWEEN ? AND ?", (sha, lo, hi))


def _block(row: sqlite3.Row) -> dict[str, Any]:
    out = {k: row[k] for k in ("id", "kind", "page", "section", "text")}
    if row["extra"]:
        out.update(json.loads(row["extra"]))
    return out


_stores: dict[Path, Store] = {}
_stores_lock = threading.Lock()


def store_for(data_dir: Path) -> Store:
    """The process's one store for a data folder."""
    root = (data_dir / "parsed").resolve()
    with _stores_lock:
        if root not in _stores:
            _stores[root] = Store(root)
        return _stores[root]


__all__ = ["KINDS", "Store", "kind_of", "store_for"]
