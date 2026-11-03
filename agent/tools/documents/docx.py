"""Word: writing a document from blocks, checking it, and replacing text in it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.documents.images import _image_size
from agent.tools.documents.markdown import Block, Run, plain


def _write_docx(blocks: list[Block], path: Path, title: str | None) -> dict[str, Any]:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    if title:
        doc.core_properties.title = title

    def add_runs(paragraph: Any, runs: list[Run]) -> None:
        for r in runs:
            run = paragraph.add_run(r.text)
            run.bold = r.bold or None
            run.italic = r.italic or None
            if r.code:
                run.font.name = "Consolas"
                run.font.size = Pt(10)

    from docx.shared import Inches

    counts = {"headings": 0, "paragraphs": 0, "list_items": 0, "tables": 0, "images": 0}
    for b in blocks:
        if b.kind == "image":
            w, _ = _image_size(Path(b.text))
            doc.add_picture(b.text, width=Inches(min(6.3, w / 96)))
            if plain(b.runs).strip():
                cap = doc.add_paragraph(style="Caption") if "Caption" in [s.name for s in doc.styles] \
                    else doc.add_paragraph()
                cap.add_run(plain(b.runs)).italic = True
            counts["images"] += 1
        elif b.kind == "heading":
            add_runs(doc.add_heading("", level=min(b.level, 9)), b.runs)
            counts["headings"] += 1
        elif b.kind in ("para", "quote"):
            p = doc.add_paragraph(style="Quote" if b.kind == "quote" else None)
            add_runs(p, b.runs)
            counts["paragraphs"] += 1
        elif b.kind == "item":
            base = "List Number" if b.ordered else "List Bullet"
            style = base if b.level == 0 else f"{base} {min(b.level + 1, 3)}"
            add_runs(doc.add_paragraph(style=style), b.runs)
            counts["list_items"] += 1
        elif b.kind == "code":
            p = doc.add_paragraph()
            run = p.add_run(b.text)
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        elif b.kind == "hr":
            doc.add_paragraph("―" * 30)
        elif b.kind == "table" and b.rows:
            width = max(len(r) for r in b.rows)
            table = doc.add_table(rows=len(b.rows), cols=width)
            table.style = "Table Grid"
            for ri, cells in enumerate(b.rows):
                for ci in range(width):
                    p = table.cell(ri, ci).paragraphs[0]
                    runs = cells[ci] if ci < len(cells) else []
                    if ri == 0:
                        runs = [Run(r.text, True, r.italic, r.code) for r in runs]
                    add_runs(p, runs)
            counts["tables"] += 1
    doc.save(str(path))
    return counts


def _check_docx(path: Path) -> None:
    from docx import Document

    Document(str(path))


__all__ = []
