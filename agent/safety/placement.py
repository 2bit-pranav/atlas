"""Where a relative path lands: the workspace, then the allowed folders, never
outside the folder it is found in. The one rule every tool and check uses."""

from __future__ import annotations

import os
from pathlib import Path


def locate(path: str, workspace: Path, folders: list[Path]) -> Path | None:
    """Where a relative path belongs: the workspace first, then each allowed
    folder. An existing file wins; a new one (`Demo/Reports/x.xlsx`) goes
    where its folder already exists. None when the path is absolute, or names
    nothing anywhere (the caller then uses the workspace).

    The one rule for relative paths, as the filesystem MCP server already
    applies it: it lists `Demo/Invoices` from an allowed folder, so the
    reader script, the file and document tools and the `read` hint must find
    the same `Demo/Invoices/x.pdf`, not look in the chat's workspace only.

    A candidate that leaves its folder (`../settings.json`) is never returned:
    a relative path only ever names something inside the folder it is found in.
    """
    if not path or path.startswith("/") or os.path.isabs(path):
        return None
    roots = [Path(workspace), *map(Path, folders)]
    inside = [(root, root / path) for root in roots if _within(root / path, root)]
    for _, candidate in inside:
        if candidate.exists():
            return candidate
    if Path(path).parent != Path("."):
        for _, candidate in inside:
            if candidate.parent.is_dir():
                return candidate
    return None


def _within(path: Path, root: Path) -> bool:
    """`path` is `root` or below it once `..` is resolved."""
    try:
        return Path(os.path.abspath(path)).is_relative_to(os.path.abspath(root))
    except (OSError, ValueError):
        return False


__all__ = ["locate"]
