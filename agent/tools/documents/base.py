"""Shared by the document writers: the file types, the error type, and the
atomic write (temp file, reopen to prove it parses, then move into place)."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: Formats `create_document` builds from Markdown. Text formats are written as is.
BINARY = {".docx", ".pdf", ".xlsx"}


TEXT = {".md", ".txt", ".csv", ".json", ".html"}


#: Never written with the plain write/edit tools.
GUARDED = BINARY | {".pptx", ".doc", ".xls"}


class DocumentError(Exception):
    """Shown to the model verbatim, so it says what to change."""


# ------------------------------------------------------------- writing --


def _atomic(path: Path, build: Callable[[Path], dict[str, Any]], check: Callable[[Path], None]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=path.suffix, prefix=".atlas-", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        info = build(tmp)
        check(tmp)
        os.replace(tmp, path)
        return info
    finally:
        tmp.unlink(missing_ok=True)


def _require(n: int, replace_all: bool, find: str, lines: list[str]) -> None:
    if n == 0:
        words = [w for w in re.findall(r"\w{4,}", find)][:3]
        near = [ln.strip() for ln in lines if any(w.lower() in ln.lower() for w in words)][:3]
        hint = (" Lines with similar words: " + " | ".join(f'"{n[:80]}"' for n in near)) if near else ""
        raise DocumentError(f'"{find[:80]}" is not in the document. `find` must match the '
                            f"text exactly, within one paragraph or cell.{hint}")
    if n > 1 and not replace_all:
        raise DocumentError(f'"{find[:80]}" appears {n} times. Give more surrounding text so '
                            "it is unique, or set replace_all to true.")


__all__ = ["BINARY", "DocumentError", "GUARDED", "TEXT"]
