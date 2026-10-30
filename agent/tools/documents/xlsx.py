"""Excel: Markdown tables (or CSV lines) as sheets, checking the file, and
replacing text in cells."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.tools.documents.base import DocumentError, _require
from agent.tools.documents.markdown import Block, Run, plain

# --------------------------------------------------------------- xlsx --

_NUMBER = re.compile(r"^[-+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")


def _cell_value(text: str) -> Any:
    """Numbers become numbers, so the sheet can sum them; everything else stays text."""
    s = text.strip()
    pct = s.endswith("%")
    core = s[:-1].strip() if pct else s
    core = core.lstrip("$€£₹")
    if _NUMBER.match(core):
        value = float(core.replace(",", ""))
        if pct:
            return value / 100
        return int(value) if value.is_integer() and "." not in core else value
    return s


def _csv_table(text: str) -> Block | None:
    import csv
    import io

    # Commas, tabs or semicolons, with the same number of cells on every line.
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    for delimiter in ("\t", ",", ";"):
        if delimiter not in lines[0]:
            continue
        rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
        if len({len(r) for r in rows}) == 1 and len(rows[0]) > 1:
            return Block("table", rows=[[[Run(c.strip())] for c in r] for r in rows])
    return None


def _write_xlsx(blocks: list[Block], path: Path, title: str | None, source: str) -> dict[str, Any]:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    tables: list[tuple[str, Block]] = []
    heading = None
    for b in blocks:
        if b.kind == "heading":
            heading = plain(b.runs)
        elif b.kind == "table":
            tables.append((heading or f"Sheet{len(tables) + 1}", b))
            heading = None
    if not tables and (csv := _csv_table(source)) is not None:
        tables.append((title or "Sheet1", csv))
    if not tables:
        raise DocumentError("an xlsx needs data: write at least one Markdown table "
                            "(| a | b |, then |---|---|, then rows), or lines separated by "
                            "commas or tabs")

    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for name, table in tables:
        safe = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
        candidate, n = safe, 2
        while candidate.lower() in used:
            candidate = f"{safe[:28]} {n}"
            n += 1
        used.add(candidate.lower())
        ws = wb.create_sheet(candidate)
        for ri, cells in enumerate(table.rows, start=1):
            for ci, runs in enumerate(cells, start=1):
                text = plain(runs)
                c = ws.cell(row=ri, column=ci, value=text if ri == 1 else _cell_value(text))
                if ri == 1:
                    c.font = Font(bold=True)
                elif isinstance(c.value, float) and plain(runs).strip().endswith("%"):
                    c.number_format = "0.0%"
        ws.freeze_panes = "A2"
        for col in ws.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, max(8, width + 2))
    wb.save(str(path))
    return {"sheets": len(tables), "rows": sum(len(t.rows) - 1 for _, t in tables)}


def _check_xlsx(path: Path) -> None:
    from openpyxl import load_workbook

    load_workbook(str(path), read_only=True).close()


def _edit_xlsx(src: Path, dst: Path, find: str, replace: str, replace_all: bool) -> int:
    from openpyxl import load_workbook

    wb = load_workbook(str(src))
    cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row
             if isinstance(c.value, str) and find in c.value]
    n = sum(c.value.count(find) for c in cells)
    _require(n, replace_all, find, [str(c.value) for c in cells])
    for c in cells if replace_all else cells[:1]:
        c.value = _cell_value(c.value.replace(find, replace, -1 if replace_all else 1))
    wb.save(str(dst))
    return n if replace_all else 1


__all__ = []
