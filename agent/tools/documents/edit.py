"""`edit_document`: replace exact text in a docx, an xlsx or a text file."""

from __future__ import annotations

from pathlib import Path

from agent.tools.documents.base import TEXT, DocumentError, _atomic, _require
from agent.tools.documents.docx import _check_docx, _edit_docx
from agent.tools.documents.xlsx import _check_xlsx, _edit_xlsx

# ------------------------------------------------------------- editing --


def edit(path: Path, find: str, replace: str, replace_all: bool = False) -> int:
    """Replace text in a document in place. Returns how many places changed."""
    if not path.is_file():
        raise DocumentError(f"no file {path.name}")
    if not find:
        raise DocumentError("`find` is empty: give the exact text to replace")
    ext = path.suffix.lower()
    if ext == ".docx":
        return _atomic(path, lambda p: {"n": _edit_docx(path, p, find, replace, replace_all)},
                       _check_docx)["n"]
    if ext == ".xlsx":
        return _atomic(path, lambda p: {"n": _edit_xlsx(path, p, find, replace, replace_all)},
                       _check_xlsx)["n"]
    if ext in TEXT:
        text = path.read_text(encoding="utf-8")
        n = text.count(find)
        _require(n, replace_all, find, text.splitlines())
        path.write_text(text.replace(find, replace, -1 if replace_all else 1), encoding="utf-8")
        return n if replace_all else 1
    if ext == ".pdf":
        raise DocumentError("a PDF cannot be edited in place: create it again with "
                            "create_document, with the change in the Markdown")
    raise DocumentError(f"cannot edit {ext} files")


__all__ = ["edit"]
