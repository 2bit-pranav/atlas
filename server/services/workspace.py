"""A chat's workspace: what it holds, and what a run created or changed."""


from __future__ import annotations

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
