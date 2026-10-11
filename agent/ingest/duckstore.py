"""Every parsed table in the installation (spec section 11.3).

One ``data.duckdb`` holds every table an ingestor or a tool produced. The rules
that matter:

* **Sheets become tables** named ``<handle>_<sheet>``. Handles are allocated
  globally, so those names are unique across every chat -- which is what lets a
  single database be shared instead of one per chat.
* **Sheets sharing a header signature also get a unified view** ``<handle>_all``
  with a ``_sheet`` column, built with ``UNION ALL BY NAME`` so a month that is
  missing a column does not drop the others' data.
* **Sheets that do not match stay separate** and are listed so ``describe`` can
  surface them rather than pretending they unified.
* **Type inference and quality warnings are recorded at ingest**, not at query
  time, so the model finds out that "revenue" has two non-numeric values in
  March *before* it computes a sum over it.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from agent.core.paths import duck_path
from agent.ingest.contract import TableSpec, sanitize_identifier

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


class _Handle:
    """One live DuckDB connection to one file, shared by every store on it.

    DuckDB refuses to open the same file twice in a process with different
    configurations ("Can't open a connection to same database file with a
    different configuration"), so a read-write ingest connection and a read-only
    tool connection to the same chat's ``data.duckdb`` cannot coexist.

    Rather than fight that, there is exactly one connection per file and
    ``read_only`` becomes a *policy* flag on the store rather than a connection
    option. The read-only guarantee for the ``query`` tool is then enforced by
    the SQL guard in :mod:`agent.tools.core_tools` -- which has to be there
    anyway, because a read-only connection still permits ``COPY ... TO`` and
    still permits ``sniff_csv``/``glob`` to read arbitrary files.
    """

    def __init__(self, path: Path) -> None:
        import duckdb

        self.path = path
        self.lock = threading.RLock()
        self.conn = duckdb.connect(str(path))
        self.refs = 0


_HANDLES: dict[str, _Handle] = {}
_HANDLES_GUARD = threading.Lock()


def _acquire(path: Path) -> _Handle:
    key = str(path)
    with _HANDLES_GUARD:
        handle = _HANDLES.get(key)
        if handle is None:
            handle = _Handle(path)
            _HANDLES[key] = handle
        handle.refs += 1
        return handle


def _release(handle: _Handle) -> None:
    with _HANDLES_GUARD:
        handle.refs -= 1
        if handle.refs <= 0:
            _HANDLES.pop(str(handle.path), None)
            try:
                handle.conn.close()
            except Exception:  # noqa: BLE001 - already closed
                pass


class DuckStore:
    """Every parsed table in the installation.

    One database, shared by all chats, because its contents are addressed by
    *handle* and handles are global: ``f1_mar`` names one table, whichever chat
    uploaded the file. Scoping this per chat bought nothing -- the tables were
    still named after a global handle -- and cost correctness, because a second
    chat uploading the same bytes was deduplicated to the first chat's
    attachment while its tables stayed put. The chat could list the file and
    then find none of its data.

    Per-chat *results* (query outputs, notes) are not here: those live in
    ``catalog_objects``, which stays chat-scoped so branch visibility (11.4)
    still works.
    """

    def __init__(
        self,
        *,
        read_only: bool = False,
        name: str = "data",
        path: Path | str | None = None,
    ) -> None:
        # No chat_id, and deliberately no way to pass one. The old signature
        # took ``(chat_id, workspace_root)`` and quietly scoped the database per
        # chat; leaving the parameters in place would just make it easy to
        # reintroduce the same split. See the class docstring.
        #
        # ``path`` exists because the ingest worker runs in a *spawned* process,
        # which re-imports the parent's ``__main__`` -- so anything the parent
        # set up at module level (env vars, a temp dir) can differ by the time
        # the child runs. The parent passes the path it actually opened and the
        # child writes to that, rather than both sides resolving it
        # independently and silently disagreeing. That disagreement is not
        # theoretical: it writes every parsed table to a database nothing reads.
        self.read_only = read_only
        self.path = Path(path) if path is not None else duck_path(name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = _acquire(self.path)
        self._lock = self._handle.lock
        self._closed = False

    # ------------------------------------------------------------ lifecycle --

    @property
    def conn(self) -> Any:
        if self._closed:
            raise RuntimeError("this DuckStore has been closed")
        return self._handle.conn

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _release(self._handle)

    def __enter__(self) -> "DuckStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --------------------------------------------------------------- tables --

    def add_table(self, name: str, data: Any) -> int:
        """Create (or replace) a table from a DataFrame or a list of row dicts.

        Everything goes through a pandas DataFrame: DuckDB's ``CREATE TABLE``
        needs declared column types, and inferring them here is exactly the
        type-inference step section 11.3 wants recorded at ingest time.
        """
        import pandas as pd

        with self._lock:
            self.conn.execute(f'DROP TABLE IF EXISTS "{name}"')

            frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(list(data or []))

            if len(frame.columns) == 0:
                # An empty sheet still deserves a table the model can describe.
                self.conn.execute(f'CREATE TABLE "{name}" ("_empty" BOOLEAN)')
                return 0

            # Register under a staging name: `register` on the final name would
            # collide with the table we are about to create.
            staging = f"__stage_{name}"
            self.conn.register(staging, frame)
            try:
                self.conn.execute(
                    f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM "{staging}"'
                )
            finally:
                self.conn.unregister(staging)
            return int(self.conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])

    def create_unified_view(
        self, view: str, tables: list[tuple[str, str]]
    ) -> int:
        """``UNION ALL BY NAME`` across (table, sheet) pairs, adding ``_sheet``.

        ``BY NAME`` is the whole point: monthly sheets drift, and a plain
        ``UNION ALL`` would drop any row whose sheet lacks a column that others
        have.
        """
        if not tables:
            return 0
        parts = []
        for table, sheet in tables:
            cols = [
                r[0]
                for r in self.conn.execute(
                    f'SELECT name FROM pragma_table_info("{table}")'
                ).fetchall()
            ]
            if not cols:
                continue
            select_list = ", ".join(f'"{c}"' for c in cols)
            parts.append(
                f"SELECT {select_list}, '{sheet}' AS \"_sheet\" FROM \"{table}\""
            )
        if not parts:
            return 0
        with self._lock:
            self.conn.execute(f'DROP VIEW IF EXISTS "{view}"')
            self.conn.execute(f'CREATE VIEW "{view}" AS ' + "\nUNION ALL BY NAME\n".join(parts))
            return int(
                self.conn.execute(f'SELECT count(*) FROM "{view}"').fetchone()[0]
            )

    def append_rows(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Append rows to an existing table (``collect`` uses this).

        Columns are matched by name and missing ones are left NULL, so a caller
        that knows only part of the schema does not have to invent the rest.
        """
        import pandas as pd

        if not rows:
            return 0
        with self._lock:
            columns = self.columns(table)
            if not columns:
                raise ValueError(f"table {table} does not exist")
            frame = pd.DataFrame([{c: r.get(c) for c in columns} for r in rows])
            staging = f"__append_{table}"
            self.conn.register(staging, frame)
            try:
                select = ", ".join(f'"{c}"' for c in columns)
                self.conn.execute(
                    f'INSERT INTO "{table}" ({select}) SELECT {select} FROM "{staging}"'
                )
            finally:
                self.conn.unregister(staging)
            return len(rows)

    def run_readonly(
        self, sql: str, *, timeout_ms: int = 5000, cancel: threading.Event | None = None
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Run a query with a hard wall-clock deadline.

        DuckDB 1.5.6 has no ``statement_timeout``; the only cancellation lever
        is ``Connection.interrupt()``. So the query runs on a worker thread and
        the caller interrupts it once the deadline passes (spike: ``interrupt()``
        lands promptly and is not sticky -- a follow-up query on the same
        connection still works).

        The lock is held for the whole thing. A DuckDB connection is not safe
        for concurrent ``execute``, and one chat has one connection, so
        serialising here is what keeps the interrupt from landing on the wrong
        query.

        Raises ``TimeoutError`` if the deadline passes.
        """
        result: dict[str, Any] = {}
        failure: list[BaseException] = []

        def work() -> None:
            try:
                cursor = self.conn.execute(sql)
                columns = [d[0] for d in cursor.description] if cursor.description else []
                result["rows"] = [dict(zip(columns, r)) for r in cursor.fetchall()]
                result["columns"] = columns
            except BaseException as exc:  # noqa: BLE001
                failure.append(exc)

        with self._lock:
            worker = threading.Thread(target=work, daemon=True)
            worker.start()

            stop_at = time.monotonic() + timeout_ms / 1000.0
            while worker.is_alive():
                remaining = stop_at - time.monotonic()
                if remaining <= 0:
                    break
                if cancel is not None and cancel.is_set():
                    break
                # ``join`` returns None, so poll on ``is_alive``.
                worker.join(min(0.02, remaining))

            if not worker.is_alive():
                if failure:
                    raise failure[0]
                return result["rows"], result["columns"]

            try:
                self.conn.interrupt()
            except Exception:  # noqa: BLE001 - best effort; the thread is daemonic
                pass
            # DuckDB checks the interrupt flag at operator boundaries, so the
            # worker can take a little longer to unwind than the deadline says.
            worker.join(5.0)

        if failure and "interrupt" in str(failure[0]).lower():
            raise TimeoutError(f"query exceeded {timeout_ms}ms")
        if failure:
            raise failure[0]
        raise TimeoutError(f"query exceeded {timeout_ms}ms")

    def table_names(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema='main' ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows]

    def columns(self, table: str) -> list[str]:
        return [
            r[0]
            for r in self.conn.execute(
                f'SELECT name FROM pragma_table_info("{table}")'
            ).fetchall()
        ]

    def row_count(self, table: str) -> int:
        try:
            return int(
                self.conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            )
        except Exception:  # noqa: BLE001 - not a table
            return 0

    def describe(self, table: str, sample: int = 5) -> dict[str, Any]:
        """Schema, a few sample rows and inferred stats, for the ``describe`` tool."""
        columns = self.columns(table)
        rows = self.conn.execute(
            f'SELECT * FROM "{table}" LIMIT {int(sample)}'
        ).fetchall()
        samples = [dict(zip(columns, row)) for row in rows]
        return {
            "table": table,
            "row_count": self.row_count(table),
            "columns": columns,
            "samples": samples,
        }

    # ------------------------------------------------------------ warnings --

    def quality_warnings(self, table: str, *, max_warnings: int = 20) -> list[str]:
        """Report columns that look numeric but are not, per column.

        Recorded at ingest so the model learns about dirty data before it sums
        a column, which is the failure mode this exists to prevent.
        """
        warnings: list[str] = []
        columns = self.columns(table)
        if not columns:
            return warnings

        for column in columns:
            try:
                stats = self.conn.execute(
                    f'SELECT count(*) AS n,'
                    f' sum(CASE WHEN "{column}" IS NOT NULL'
                    f' AND trim(CAST("{column}" AS VARCHAR)) != \'\''
                    f' THEN 1 ELSE 0 END) AS filled,'
                    f' sum(CASE WHEN try_cast("{column}" AS DOUBLE) IS NOT NULL'
                    f' AND "{column}" IS NOT NULL'
                    f' AND trim(CAST("{column}" AS VARCHAR)) != \'\' THEN 1 ELSE 0 END)'
                    f' AS numeric'
                    f' FROM "{table}"'
                ).fetchone()
            except Exception:  # noqa: BLE001 - unsupported type
                continue
            total = int(stats[0] or 0)
            if total == 0:
                continue
            numeric = int(stats[2] or 0)
            if numeric == 0:
                continue          # genuinely a text column
            bad = total - numeric
            if bad:
                examples = self.conn.execute(
                    f'SELECT DISTINCT CAST("{column}" AS VARCHAR) AS v FROM "{table}"'
                    f' WHERE "{column}" IS NOT NULL'
                    f' AND trim(CAST("{column}" AS VARCHAR)) != \'\''
                    f' AND try_cast("{column}" AS DOUBLE) IS NULL LIMIT 3'
                ).fetchall()
                sample = ", ".join(str(r[0]) for r in examples)
                warnings.append(
                    f'{table}.{column} has {bad} non-numeric value(s) of {total}'
                    + (f" (e.g. {sample})" if sample else "")
                )
                if len(warnings) >= max_warnings:
                    break
        return warnings


# ------------------------------------------------------------- registration --


def group_by_header(sheets: dict[str, list[str]]) -> dict[str, list[str]]:
    """Group sheet names by their header signature.

    Sheets with identical headers unify; the rest are listed separately so the
    UI can say "these did not match" rather than silently dropping them.
    """
    groups: dict[str, list[str]] = {}
    for sheet, columns in sheets.items():
        key = "|".join(sanitize_identifier(c) for c in columns)
        groups.setdefault(key, []).append(sheet)
    return groups


def register_tables(
    store: DuckStore, specs: list[TableSpec], handle: str
) -> tuple[list[TableSpec], list[str]]:
    """Write every sheet as its own table, plus the unified view.

    Section 11.3: sheets become tables named ``<handle>_<sheet>``, and sheets
    sharing a header signature are *also* exposed as one ``<handle>_all`` view.
    Both exist: per-sheet tables keep the original column types, while the view
    is what a query spans months with.

    Quality warnings are *not* computed here. The ingestor already reported
    them against the source values -- naming the offending values, which is
    impossible once they have become NULL -- so re-checking in SQL would only
    produce a worse duplicate. ``DuckStore.quality_warnings`` stays available
    for tables that arrive from elsewhere, such as a tool's query result.
    """
    warnings: list[str] = []
    registered: list[TableSpec] = []

    for spec in specs:
        count = store.add_table(spec.name, spec.data)
        registered.append(TableSpec(
            name=spec.name, sheet=spec.sheet, rows=count,
            columns=spec.columns, data=None, in_unified=spec.in_unified,
        ))

    unified = [s for s in specs if s.in_unified]
    if len(unified) > 1:
        view = f"{handle}_all"
        pairs = [(s.name, s.sheet or s.name) for s in unified]
        count = store.create_unified_view(view, pairs)
        columns = store.columns(view)
        registered.append(TableSpec(
            name=view, sheet=None, rows=count, columns=columns,
            data=None, in_unified=True,
        ))

    return registered, warnings


__all__ = ["DuckStore", "group_by_header", "register_tables"]
