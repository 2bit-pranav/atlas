"""Edits addressed by what the readers print: a docx block id, a spreadsheet cell.

The baseline's edits failed 7 of 8 times (decisions.md, 2026-11-03) because
the reader showed a table row as `| Brightline | 9.85 | 23 days |` and the
edit tool matched text within one cell, and because no tool could change a
number in a spreadsheet (`edit_document` only matched text cells). Here the
model names the place (`t1.r3.c3`, `Mar!B2`) and the new content.

Ids follow agent/ingest/parse.py: `b12` is the 12th paragraph directly in the
document body (empty ones counted), `t1` the first body table, its rows and
cells counted from 1 the way python-docx lists them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.tools.documents.base import DocumentError
from agent.tools.documents.xlsx import _as_text, _cell_value


def _body(doc: Any) -> tuple[list[Any], list[Any]]:
    """The body's own paragraphs and tables, in order (not those inside tables)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    paragraphs, tables = [], []
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraphs.append(Paragraph(child, doc))
        elif child.tag.endswith("}tbl"):
            tables.append(Table(child, doc))
    return paragraphs, tables


def _set_text(paragraph: Any, text: str) -> None:
    """New text in the paragraph's first run, so it keeps that run's formatting.
    The other runs are emptied, not removed: a run can hold a picture."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def edit_docx_block(src: Path, dst: Path, block: str, text: str) -> str:
    """Replace one block's text; returns the old text."""
    from docx import Document

    doc = Document(str(src))
    paragraphs, tables = _body(doc)
    block = block.strip()
    if m := re.fullmatch(r"b(\d+)", block):
        n = int(m[1])
        if not 1 <= n <= len(paragraphs):
            raise DocumentError(f"no block {block}: paragraphs are b1-b{len(paragraphs)}.")
        target = paragraphs[n - 1]
        old = target.text
        _set_text(target, text)
    elif m := re.fullmatch(r"t(\d+)\.r(\d+)\.c(\d+)", block):
        t, r, c = (int(g) for g in m.groups())
        if not 1 <= t <= len(tables):
            raise DocumentError(f"no table t{t}: the document has {len(tables)} table(s).")
        rows = tables[t - 1].rows
        if not 1 <= r <= len(rows):
            raise DocumentError(f"no row r{r} in t{t}: rows are r1-r{len(rows)}.")
        cells = rows[r - 1].cells
        if not 1 <= c <= len(cells):
            raise DocumentError(f"no column c{c} in t{t}: columns are c1-c{len(cells)}.")
        cell = cells[c - 1]
        old = cell.text
        first, *rest = cell.paragraphs
        _set_text(first, text)
        for p in rest:
            p._p.getparent().remove(p._p)
    else:
        raise DocumentError(f"{block!r} is not a block id. Use the id read_docx printed: a paragraph "
                            "like b12, or a table cell like t1.r3.c2 (row 3, column 2).")
    doc.save(str(dst))
    return old


_CELL = re.compile(r"(?:(?P<sheet>'[^']+'|[^!]+)!)?(?P<cell>[A-Za-z]{1,3}[0-9]{1,7})")


def set_xlsx_cell(src: Path, dst: Path, cell: str, value: str, sheet: str = "") -> tuple[str, str, Any]:
    """Set one cell; returns (sheet, cell, old value). A number becomes a number;
    text starting with `=` stays text (formula injection, B19)."""
    from openpyxl import load_workbook

    m = _CELL.fullmatch(cell.strip())
    if not m:
        raise DocumentError(f"{cell!r} is not a cell. Give one like B2 or Mar!B2.")
    name = (m["sheet"] or sheet or "").strip("'")
    wb = load_workbook(str(src), keep_vba=src.suffix.lower() == ".xlsm")
    if name and name not in wb.sheetnames:
        raise DocumentError(f"no sheet {name!r}. Sheets: {', '.join(wb.sheetnames)}.")
    ws = wb[name] if name else wb.worksheets[0]
    target = ws[m["cell"].upper()]
    old = target.value
    target.value = _cell_value(value)
    _as_text(target)
    wb.save(str(dst))
    return ws.title, m["cell"].upper(), old


__all__ = ["edit_docx_block", "set_xlsx_cell"]
