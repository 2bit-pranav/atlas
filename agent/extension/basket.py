"""The extension's file basket: files on the user's computer that Atlas found
for a form's upload fields, offered as cards the user drags onto the page.

A basket entry is a reference, not a copy: a random id for one file the fill
search found in the allowed folders, valid for a while. The file is read when
it is dragged or downloaded, and checked again then: still there, still inside
the allowed folders, not Atlas's own files, not too large. Nothing is uploaded
by Atlas; the user drops each file where it goes.

Candidates come from the same search as the agent's `find_files`
(`agent/tools/finding.rank`): words of the field's label in a file's name,
folder or text, and the types the field accepts.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import paths
from agent.config.settings import Settings
from agent.safety.protected import Protected
from agent.safety.scope import Scope
from agent.tools.finding import rank

#: How long a card can be dragged after Fill found it.
TTL_SECONDS = 2 * 60 * 60
MAX_BYTES = 25 * 1024 * 1024
MAX_ENTRIES = 40


@dataclass
class Entry:
    path: Path
    field: str
    size: int
    mtime: float
    expires: float


class Basket:
    """The references handed out, by id. In memory: a restart empties the basket."""

    def __init__(self) -> None:
        self._items: dict[str, Entry] = {}

    def offer(self, path: Path, field: str) -> str:
        now = time.time()
        self._items = {k: v for k, v in self._items.items() if v.expires > now}
        while len(self._items) >= MAX_ENTRIES:
            self._items.pop(next(iter(self._items)))
        key = f"b-{secrets.token_urlsafe(12)}"
        st = path.stat()
        self._items[key] = Entry(path, field, st.st_size, st.st_mtime, now + TTL_SECONDS)
        return key

    def get(self, key: str) -> Entry | None:
        entry = self._items.get(key)
        return entry if entry and entry.expires > time.time() else None


def _scope(settings: Settings) -> Scope:
    folders = [Path(f).expanduser() for f in settings.access.folders if f.strip()]
    # A workspace no chat has: with none, Protected would let every chat's files through.
    nowhere = paths.data_dir(settings) / "chats" / "_basket"
    return Scope(workspace=nowhere, folders=folders,
                 protected=Protected(root=paths.ROOT, data=paths.data_dir(settings),
                                     mcp_config=paths.mcp_config(settings), workspace=nowhere))


def refusal(settings: Settings, path: Path) -> str | None:
    """Why this file may not be handed to a page now, or None."""
    scope = _scope(settings)
    try:
        target = path.resolve(strict=True)
    except OSError:
        return "the file is no longer there"
    if not target.is_file():
        return "the file is no longer there"
    if not any(target.is_relative_to(f.resolve()) for f in scope.folders if f.exists()):
        return "the file is not in your allowed folders"
    if scope.protected and scope.protected.refuses(target, write=False):
        return "Atlas's own files are never handed out"
    if target.stat().st_size > MAX_BYTES:
        return f"the file is over {MAX_BYTES // (1024 * 1024)} MB"
    return None


def _kind(accept: str) -> str:
    """A field's `accept` (".pdf,image/*") as find_files' kind words ("pdf image")."""
    out = []
    for part in re.split(r"[,\s]+", accept.lower()):
        if part.startswith("."):
            out.append(part[1:])
        elif part.startswith("image/"):
            out.append("image")
        elif part == "application/pdf":
            out.append("pdf")
        elif "word" in part:
            out.append("word")
    return " ".join(dict.fromkeys(out))


def _entries(folder: Path) -> int:
    try:
        return sum(1 for _ in folder.iterdir())
    except OSError:
        return 0


def candidates(settings: Settings, label: str, accept: str = "", limit: int = 4) -> list[Path]:
    """The files in the allowed folders that best match an upload field ("Upload your resume")."""
    scope = _scope(settings)
    bases = [f.resolve() for f in scope.folders if f.is_dir()]
    if not bases:
        return []
    # Smallest folders first: the search has one budget for all of them, and a Desktop of 60,000
    # files would spend it before a small "Resume" folder was reached.
    bases.sort(key=_entries)
    ranked = rank(scope, bases, label, _kind(accept))
    return [p for p, entry in ranked if entry["hits"] and refusal(settings, p) is None][:limit]


def shown(settings: Settings, path: Path) -> str:
    """Where a file is, as the user knows it: "Documents/Career"."""
    for folder in (Path(f).expanduser().resolve() for f in settings.access.folders if f.strip()):
        if path.resolve().is_relative_to(folder):
            rel = path.resolve().parent.relative_to(folder)
            return f"{folder.name}/{rel.as_posix()}".rstrip("/.") if str(rel) != "." else folder.name
    return path.parent.name


def card(settings: Settings, key: str, entry: Entry) -> dict[str, Any]:
    """A basket card: what it is, where it lives, and whether it is still as Fill found it."""
    why = refusal(settings, entry.path)
    now = entry.path.stat() if why is None else None
    return {"id": key, "name": entry.path.name, "folder": shown(settings, entry.path), "field": entry.field,
            "size": now.st_size if now else entry.size, "available": why is None, "problem": why,
            "changed": bool(now and (now.st_size != entry.size or now.st_mtime != entry.mtime))}


__all__ = ["Basket", "Entry", "MAX_BYTES", "candidates", "card", "refusal", "shown"]
