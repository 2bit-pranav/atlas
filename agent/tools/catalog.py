"""Object catalog (spec section 5, "Catalog and objects").

Three rules that the tools depend on:

* **Objects are immutable.** Nothing is edited in place; a derived object is a
  new object. Every number therefore has recorded lineage.
* **Every object knows its provenance** -- the SQL or tool call that made it.
* **Branch visibility.** An object is reachable only if it was created by a node
  on the current path. That check lives in ``ToolContext.resolve``; this module
  just stores ``node_id`` so that check is possible.

Nothing here reads from DuckDB or SQLite on the *other* side -- a catalog row
records which store holds the body, and the tool that knows the kind goes and
gets it.
"""

from __future__ import annotations

from typing import Any

from agent.core.repo import CatalogObject, Repo

KINDS = ("table", "text", "file", "draft", "image")
STORES = ("duckdb", "sqlite", "disk")


class Catalog:
    """Read/write access to ``catalog_objects``."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    def add(
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
        if kind not in KINDS:
            raise ValueError(f"unknown object kind {kind!r}")
        if store not in STORES:
            raise ValueError(f"unknown store {store!r}")
        return self.repo.add_object(
            chat_id=chat_id, name=name, kind=kind, store=store, run_id=run_id,
            step_id=step_id, node_id=node_id, schema=schema, row_count=row_count,
            tokens=tokens, provenance=provenance,
        )

    def get(self, object_id: str) -> CatalogObject | None:
        try:
            row = self.repo.db.connection.execute(
                "SELECT * FROM catalog_objects WHERE id=?", (object_id,)
            ).fetchone()
        except Exception:  # noqa: BLE001
            return None
        if row is None:
            return None
        from agent.core.repo import _object

        return _object(row)

    def find(self, chat_id: str, name: str) -> CatalogObject | None:
        """Look up by the name the model was given (e.g. ``r3``, ``monthly``)."""
        row = self.repo.db.connection.execute(
            "SELECT * FROM catalog_objects WHERE chat_id=? AND name=?"
            " ORDER BY rowid DESC LIMIT 1",
            (chat_id, name),
        ).fetchone()
        if row is None:
            return None
        from agent.core.repo import _object

        return _object(row)

    def list(self, chat_id: str) -> list[CatalogObject]:
        return self.repo.objects(chat_id)

    # ------------------------------------------------------------ text body --

    def put_text(self, object_id: str, body: str) -> None:
        """Store the body of a text object, FTS-indexed (section 5)."""
        with self.repo.db.write() as conn:
            conn.execute(
                "INSERT INTO text_objects (object_id, body) VALUES (?,?)"
                " ON CONFLICT(object_id) DO UPDATE SET body=excluded.body",
                (object_id, body),
            )

    def get_text(self, object_id: str) -> str | None:
        try:
            row = self.repo.db.connection.execute(
                "SELECT body FROM text_objects WHERE object_id=?", (object_id,)
            ).fetchone()
        except Exception:  # noqa: BLE001
            return None
        return row["body"] if row else None


__all__ = ["Catalog", "KINDS", "STORES"]
