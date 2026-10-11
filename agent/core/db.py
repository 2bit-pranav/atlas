"""SQLite connection and transaction management.

Conventions from section 5: WAL, foreign keys on, integer epoch-ms timestamps,
JSON stored as TEXT.

Threading model: one connection guarded by a reentrant lock. Atlas is a
single-user local app with exactly one active run (section 2), so a connection
pool would add contention handling for a concurrency level that cannot occur.
What *can* occur is concurrent event appends from the run executor, the SSE
fan-out and cancel handling, and those are serialised here.

``write()`` is reentrant: nested calls join the outer transaction instead of
starting a second one, so a repository method that calls another still commits
atomically. That is what makes ``finalize_run`` a single transaction no matter
how many helpers it is built from.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
)


class Database:
    """A SQLite connection with explicit, reentrant transactions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)

        # isolation_level=None puts the driver in autocommit mode so that
        # transactions are exactly what we write, not what the driver infers.
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._depth = 0
        self._closed = False

        for pragma in PRAGMAS:
            self._conn.execute(pragma)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any exception.

        IMMEDIATE takes the write lock up front so two writers fail fast on
        ``busy`` instead of deadlocking on a deferred-to-commit upgrade.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("database is closed")
            outermost = self._depth == 0
            if outermost:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.execute("COMMIT")

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """A read transaction; joins an enclosing write if one is open."""
        with self._lock:
            if self._closed:
                raise RuntimeError("database is closed")
            if self._depth > 0:
                yield self._conn
                return
            self._conn.execute("BEGIN")
            self._depth += 1
            try:
                yield self._conn
            finally:
                self._depth -= 1
                self._conn.execute("COMMIT")

    def in_transaction(self) -> bool:
        return self._depth > 0

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            # Roll back anything a crashed writer left open before closing.
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            self._conn.close()
            self._closed = True

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def is_unique_violation(exc: sqlite3.IntegrityError) -> bool:
    return isinstance(exc, sqlite3.IntegrityError) and "UNIQUE" in str(exc).upper()


__all__ = ["PRAGMAS", "Database", "is_unique_violation"]
