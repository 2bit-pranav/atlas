"""A chat's workspace: what it holds, and what a run created or changed."""


from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.recovery.done_check import document_problem, scan

_scan = scan   # the agent's done check scans the same way (agent/recovery/done_check.py)


def _changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]],
             root: Path | None = None) -> list[dict[str, Any]]:
    """Files a run created or modified, for the download chips under its answer.
    A document that does not open says so (`broken`): the chip must not offer it as done."""
    out = []
    for name, (size, mtime) in sorted(after.items()):
        if name not in before:
            entry: dict[str, Any] = {"name": name, "size": size, "change": "created"}
        elif before[name] != (size, mtime):
            entry = {"name": name, "size": size, "change": "modified"}
        else:
            continue
        if root is not None and (problem := document_problem(root / name)) is not None:
            entry["broken"] = problem
        out.append(entry)
    return out


__all__ = []


#: Windows device names: a file called `CON` or `nul.txt` cannot be created.
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_name(raw: str) -> str:
    """An uploaded file's name, safe to create in the workspace.

    Only the last path part is kept; characters Windows forbids become `_`;
    trailing dots and spaces (which Windows drops) go; `..`, `.`, empty and
    device names (`CON`) get a usable name. A leading dot is replaced, so the
    file is not hidden from the workspace listing.
    """
    name = re.split(r"[\\/]", raw or "")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).rstrip(" .").lstrip(" ")
    if not name.strip("."):
        return "upload.bin"
    if name.startswith("."):
        name = "_" + name[1:]
    if name.split(".")[0].lower() in _RESERVED:
        name = "_" + name
    return name[:180]


def unique_path(folder: Path, name: str) -> Path:
    """`folder/name`, or `name (2).ext` and so on when that is taken: an earlier
    message's history points at the file already there."""
    target = folder / name
    stem, suffix, n = Path(name).stem, Path(name).suffix, 2
    while target.exists():
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target
