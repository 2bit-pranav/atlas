"""A chat's workspace: what it holds, and what a run created or changed."""


from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _scan(root: Path) -> dict[str, tuple[int, int]]:
    """`relative/path -> (size, mtime_ns)` for every file in a workspace."""
    out: dict[str, tuple[int, int]] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        # Dot-files and dot-folders are Atlas's own bookkeeping (temp files,
        # images a reader extracted): not the user's files, not download chips.
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def _changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[dict[str, Any]]:
    """Files a run created or modified, for the download chips under its answer."""
    out = []
    for name, (size, mtime) in sorted(after.items()):
        if name not in before:
            out.append({"name": name, "size": size, "change": "created"})
        elif before[name] != (size, mtime):
            out.append({"name": name, "size": size, "change": "modified"})
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
