"""`create_document`: Markdown to docx, pdf, xlsx or a text file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.tools.documents.base import BINARY, TEXT, DocumentError, _atomic
from agent.tools.documents.docx import _check_docx, _write_docx
from agent.tools.documents.images import _resolve_images
from agent.tools.documents.markdown import parse_markdown
from agent.tools.documents.pdf import _check_pdf, _write_pdf
from agent.tools.documents.xlsx import _check_xlsx, _write_xlsx


def create(path: Path, content: str, title: str | None = None, base: Path | None = None,
           asset: Callable[[str], Path | None] | None = None) -> dict[str, Any]:
    """Write `content` (Markdown) to `path` in the format its extension names.

    Relative image paths are taken from `base` (the chat workspace). Images
    that do not exist are left out and reported as `missing_images`.
    """
    ext = path.suffix.lower()
    if ext in TEXT:
        def build_text(p: Path) -> dict[str, Any]:
            p.write_text(content, encoding="utf-8")
            return {}
        return _atomic(path, build_text, lambda p: None)
    if ext not in BINARY:
        raise DocumentError(f"cannot create {ext or 'a file without an extension'}: "
                            f"use one of {', '.join(sorted(BINARY | TEXT))}")
    if not content.strip():
        raise DocumentError("content is empty: write the document as Markdown")
    blocks = parse_markdown(content)
    missing = _resolve_images(blocks, base or path.parent, asset)
    if ext == ".docx":
        info = _atomic(path, lambda p: _write_docx(blocks, p, title), _check_docx)
        return {**info, "missing_images": missing}
    if ext == ".pdf":
        info = _atomic(path, lambda p: _write_pdf(blocks, p, title), _check_pdf)
        return {**info, "missing_images": missing}
    return _atomic(path, lambda p: _write_xlsx(blocks, p, title, content), _check_xlsx)


__all__ = ["create"]
