"""Images in a document: where they are, and their size."""

from __future__ import annotations

from pathlib import Path

from agent.tools.documents.markdown import Block

# --------------------------------------------------------------- docx --


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def _resolve_images(blocks: list[Block], base: Path | None) -> list[str]:
    """Point every image block at a real file. Returns the ones that are missing."""
    from agent.platform.winpaths import windows_path

    missing = []
    for b in blocks:
        if b.kind != "image":
            continue
        src = b.text.strip().strip("<>")
        p = Path(windows_path(src)) if src.startswith("/") else Path(src)
        if not p.is_absolute() and base is not None:
            p = base / p
        if p.is_file():
            b.text = str(p)
        else:
            missing.append(src)
            b.kind = "missing"
    return missing


__all__ = []
