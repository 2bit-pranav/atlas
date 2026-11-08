"""Shared by the document writers: the file types, the error type, and the
atomic write (temp file, reopen to prove it parses, then move into place)."""

from __future__ import annotations

import os
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


__all__ = ["BINARY", "DocumentError", "GUARDED", "TEXT"]
