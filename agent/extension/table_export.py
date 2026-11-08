"""A table from a web page, saved as xlsx or csv. Code only, no model."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_NUMBER = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _cell(value: str) -> Any:
    """A number stays a number in the sheet; "007" and phone numbers stay text."""
    text = value.strip()
    if _NUMBER.fullmatch(text) and not (len(text) > 1 and text.startswith("0") and "." not in text[:2]):
        number = float(text.replace(",", ""))
        return int(number) if number.is_integer() and "." not in text else number
    return text


def _csv_cell(value: str) -> str:
    """A spreadsheet opening a CSV runs a cell starting with = + - @ as a
    formula; a leading ' keeps it text. Negative numbers are left alone."""
    if value[:1] in ("=", "+", "-", "@", "\t", "\r") and not _NUMBER.fullmatch(value.strip()):
        return "'" + value
    return value


def write_table(rows: list[list[str]], title: str, url: str, fmt: str, folder: str = "") -> Path:
    """Save a page's table as .xlsx or .csv; returns the file.

    Used by the extension's "Save table" button. The content script has
    already turned the table into rows (merged cells expanded).
    """
    import csv

    if fmt not in ("xlsx", "csv"):
        raise ValueError('format must be "xlsx" or "csv"')
    if not rows:
        raise ValueError("the table is empty")
    target = Path(folder).expanduser() if folder.strip() else Path.home() / "Downloads" / "Atlas"
    if not target.is_absolute():
        raise ValueError(f"the folder must be a full path, not {folder!r}")
    target.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "-", title.lower()).strip("-")[:60] or "table"
    path = target / f"{stem}.{fmt}"
    n = 2
    while path.exists():
        path = target / f"{stem}-{n}.{fmt}"
        n += 1
    if fmt == "csv":
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerows([[_csv_cell(c) for c in row] for row in rows])
        return path
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Table")
    ws.title = (re.sub(r"[\[\]:*?/\\]", " ", title).strip() or "Table")[:31]
    for r, row in enumerate(rows):
        ws.append([_cell(c) if r else c for c in row])
    for line in ws.iter_rows():
        for cell in line:
            if cell.data_type == "f":    # page text starting with = stays text
                cell.data_type = "s"
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for column in ws.columns:
        width = max(len(str(c.value or "")) for c in column)
        ws.column_dimensions[column[0].column_letter].width = min(60, max(8, width + 2))
    if url:
        ws.cell(row=ws.max_row + 2, column=1, value=f"Source: {url}")
    wb.save(path)
    return path


__all__ = ["write_table"]
