"""ToolContext: what a tool is allowed to reach (spec section 11.5).

Tools never see paths, connections or the filesystem directly. They get this,
and it hands out exactly what they need and nothing more -- which is what keeps
"handles, not paths" (section 11.1) enforceable rather than aspirational.

The one security-relevant method is :meth:`resolve`, which is the whole of
branch visibility (section 11.4): a tool may only touch an object if it belongs
to the current chat *and* was created by a node on the visible path.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.core.repo import Repo, Run
from agent.ingest.attachments import AttachmentStore
from agent.ingest.duckstore import DuckStore
from agent.tools.catalog import Catalog
from agent.tools.contract import ToolError

#: ``f1``, ``f1_sales.xlsx``, ``F1``. The leading handle is the reliable part;
#: the filename is decoration the model bolts on. Note the lookahead uses an
#: explicit class rather than ``\b``: ``_`` counts as a word character, so
#: ``\b`` fails exactly on ``f1_sales.xlsx`` -- the case that matters.
_HANDLE_RE = re.compile(r"^([A-Za-z]+\d+)(?![A-Za-z0-9])")


def _handle_candidates(text: str) -> list[str]:
    """Handle spellings to try, most literal first."""
    stripped = text.strip()
    candidates = [stripped, stripped.lower()]
    match = _HANDLE_RE.match(stripped)
    if match:
        candidates.append(match.group(1).lower())
    return [c for c in dict.fromkeys(candidates) if c]


@dataclass
class ToolContext:
    """Per-run tool context."""

    repo: Repo
    run: Run
    chat_id: str
    node_id: str
    #: Per-chat scratch directory. Working files only -- parsed data is global.
    workspace: Path
    settings: dict[str, Any] = field(default_factory=dict)
    #: Cancelled from the API; long tools poll this (section 9).
    cancel: threading.Event = field(default_factory=threading.Event)
    #: Emit an event mid-tool, e.g. progress on a slow query.
    emit: Callable[[str, Any], None] | None = None
    _attachments: AttachmentStore | None = None
    _duck: DuckStore | None = None
    _duck_writable: DuckStore | None = None
    _catalog: Catalog | None = None
    _visible_node_ids: set[str] | None = None

    # ------------------------------------------------------------- services --

    @property
    def attachments(self) -> AttachmentStore:
        if self._attachments is None:
            self._attachments = AttachmentStore(self.repo.db)
        return self._attachments

    @property
    def duck(self) -> DuckStore:
        """The shared DuckDB, for reading.

        One database for the whole installation, not one per chat: its tables
        are named after globally-unique handles, so every chat that has a file
        sees that file's tables. The read-only *policy* is enforced in the SQL
        guard (section 11.3) -- a read-only DuckDB connection still permits
        ``COPY ... TO`` and ``sniff_csv``, so the connection flag was never the
        boundary anyway.
        """
        if self._duck is None:
            self._duck = DuckStore(read_only=True)
        return self._duck

    def duck_write(self) -> DuckStore:
        """The same store, writable, for ``collect`` only.

        Deliberately a separate accessor from ``duck``: every other tool reads,
        and a typo cannot turn into a write through the read path. Collector
        tables are named ``collect_<name>`` and are shared too -- they are
        derived from file content, not from a conversation.
        """
        if self._duck_writable is None:
            self._duck_writable = DuckStore(read_only=False)
        return self._duck_writable

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            self._catalog = Catalog(self.repo)
        return self._catalog

    # ----------------------------------------------------------- visibility --

    def visible_node_ids(self) -> set[str]:
        """Node ids on the visible path, computed once per run."""
        if self._visible_node_ids is None:
            self._visible_node_ids = {
                n.id for n in self.repo.visible_path(self.chat_id)
            }
        return self._visible_node_ids

    def resolve(self, object_id: str) -> dict[str, Any]:
        """Resolve an object id, enforcing branch visibility.

        An object is reachable only if it is an attachment of this chat or was
        created by a node on the current path. Anything else is reported as
        ``not_found`` rather than ``forbidden``: the model gains nothing from
        learning that an id exists on another branch.
        """
        obj = self.catalog.get(object_id)
        known = [o.id for o in self.catalog.list(self.chat_id)[-10:]]
        if obj is None or (obj.node_id and obj.node_id not in self.visible_node_ids()):
            raise ToolError(
                "not_found", f"no object {object_id!r} in this chat", known or ["none yet"]
            )
        return obj

    def resolve_handle(self, handle: str) -> dict[str, Any]:
        """Resolve an ``f1``-style attachment handle within this chat.

        Forgiving about how the model spells it, because it composes the
        handle with the filename it just read in a ``list_files`` listing:
        ``f1_sales.xlsx``, ``sales.xlsx`` and ``f1`` all mean f1. Measured on
        the real model -- shown ``f1  sales.xlsx`` it wrote
        ``f1_sales.xlsx``, got an error, and then gave up on the file entirely.
        """
        valid = [a["handle"] for a in self.attachments.attachments_for_chat(self.chat_id)]
        for candidate in _handle_candidates(handle):
            try:
                attachment = self.attachments.attachment_by_handle(candidate)
            except Exception:  # noqa: BLE001 - the store raises its own not-found
                continue
            if self.handle_visible(attachment["id"]):
                return attachment

        # Last resort: the model passed the filename instead of the handle.
        # Matched against every name this content has been uploaded under, so a
        # file the user just called resume_new.pdf still resolves to the handle
        # that was minted when it was called resume.pdf.
        wanted = handle.strip().casefold()
        for attachment in self.attachments.attachments_for_chat(self.chat_id):
            for name in self.attachments.all_names(attachment["id"]):
                stem = Path(str(name)).stem
                if wanted in (str(name).casefold(), stem.casefold()):
                    return attachment

        # And the other last resort: the raw attachment id. The user's message
        # carries one, so it is the one identifier the model can reach for
        # without calling a tool first -- and it did, handing
        # ``01M4MX5X9DQ...`` straight to ``outline``. Resolving it costs one
        # indexed lookup and turns a dead end into a working call.
        for attachment in self.attachments.attachments_for_chat(self.chat_id):
            if wanted == str(attachment["id"]).casefold() and self.handle_visible(
                attachment["id"]
            ):
                return attachment

        raise ToolError(
            "not_found", f"no attachment {handle!r} in this chat", valid or ["none yet"]
        )

    # ---------------------------------------------------------------- tables --

    def table_name(self, name: str) -> str:
        """Resolve a table name the model wrote, forgivingly but exactly.

        Table names are lowercased by the ingestor (``f1_mar``), but the model
        naturally writes the sheet name it just read (``f1_Mar``) or the word
        the user typed (``f1_March``). Rather than failing on a case
        difference, resolve it -- and only accept a guess that is unambiguous.
        Anything still unresolvable raises with the full valid list, which is
        what gets the model back on track.
        """
        import re

        tables = self.duck.table_names()
        if name in tables:
            return name

        wanted = name.strip('"').lower()
        exact_ci = [t for t in tables if t.lower() == wanted]
        if len(exact_ci) == 1:
            return exact_ci[0]
        if len(exact_ci) > 1:
            raise ToolError("bad_arg", f"{name!r} is ambiguous", sorted(exact_ci))

        # Strip a trailing month-ish word: f1_March -> f1_mar, f1_Jan -> f1_jan.
        stem = re.sub(r"_(march|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
                      lambda m: "_" + m.group(1)[:3], wanted)
        if stem != wanted:
            hit = [t for t in tables if t.lower() == stem]
            if len(hit) == 1:
                return hit[0]

        contains = [t for t in tables if wanted and wanted in t.lower()]
        if len(contains) == 1:
            return contains[0]

        raise ToolError("not_found", f"no table named {name!r}", sorted(tables))

    def handle_visible(self, attachment_id: str) -> bool:
        for a in self.attachments.attachments_for_chat(self.chat_id):
            if a["id"] == attachment_id:
                return True
        return False

    # ---------------------------------------------------------------- guards --

    def check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise ToolError("failed", "cancelled")

    def limit(self) -> dict[str, Any]:
        """Result budgets from settings (section 10)."""
        return self.settings.get("results", {}) or {}


__all__ = ["ToolContext"]
