"""Data from other files, put into a new document by code instead of retyped.

In `create_document`'s Markdown, a reference on its own line becomes a table:

    {{report.docx#t1}}                 table 1 of a Word document, as read_docx numbers it
    {{sales.xlsx!North!A1:C41}}        a range of a sheet (the first row is the header)
    {{sales.xlsx!A1:C41}}              a range of the first sheet
    {{sales.xlsx sql: SELECT ...}}     a query over the workbook's sheets, as read_xlsx runs it
    {{orders.csv sql: SELECT ...}}     a query over a CSV file (the table is named after it)

Retyped, the data came out wrong: a total of 6,776.70 for 7,260.44, rows dropped
or changed (2026-11-12). Each file is checked like any read (`call_paths`, `grid`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from agent.tools.documents.base import DocumentError

REFERENCE = re.compile(
    r"\{\{\s*(?P<file>[^{}#!\n]+?\.(?:docx|xlsx|xlsm|csv))\s*"
    r"(?:#t(?P<table>\d+)|!(?P<range>[^{}\n]+?)|sql:\s*(?P<sql>[^{}]+?))\s*\}\}", re.I)
#: Rows one reference may put in a document.
MAX_ROWS = 5000


def referenced(content: str) -> list[str]:
    """The files the references in `content` name, as written."""
    return [m.group("file").strip() for m in REFERENCE.finditer(content)]


def expand(content: str, resolve: Callable[[str], Path]) -> str:
    """`content` with each reference replaced by its data as a Markdown table."""
    def one(m: re.Match[str]) -> str:
        line_start = content.rfind("\n", 0, m.start()) + 1
        line_end = content.find("\n", m.end())
        inline = bool(content[line_start:m.start()].strip() or content[m.end():None if line_end < 0 else line_end].strip())
        name = m.group("file").strip()
        path = resolve(name)
        if not path.is_file():
            raise DocumentError(f"{m.group(0)}: there is no file {name}.")
        if inline:
            # In a sentence or a table cell: one value fits there (a total), a table does not.
            # The model put a total's query in the Total row three times over (2026-11-14).
            if m.group("sql"):
                header, rows = _query_rows(path, m.group("sql").strip(), m.group(0))
                if len(rows) == 1 and len(rows[0]) == 1:
                    from agent.tools.doc_reading import cell_str

                    return cell_str(rows[0][0])
            raise DocumentError(f"{m.group(0)} is inside a line: there it must give one value, like "
                                "{{f.csv sql: SELECT ROUND(SUM(amount), 2) FROM f}}. A table goes on a line of its own.")
        try:
            if m.group("table"):
                return _docx_table(path, int(m.group("table")), m.group(0))
            if m.group("range"):
                return _range(path, m.group("range").strip(), m.group(0))
            return _query(path, m.group("sql").strip(), m.group(0))
        except DocumentError:
            raise
        except Exception as exc:  # noqa: BLE001 - the model needs to know which reference failed
            raise DocumentError(f"{m.group(0)} could not be read: {type(exc).__name__}: {exc}") from exc
    out = REFERENCE.sub(one, content)
    if left := re.search(r"\{\{[^\n]{0,80}", out):
        # Not closed, or not a form this reads: it would have gone into the document as text.
        raise DocumentError(f"{left.group(0)} is not a reference that can be read. Write it whole on a line of "
                            'its own, two braces each side: {{file.xlsx sql: SELECT ... FROM "Sheet" ...}}, '
                            "{{file.csv sql: SELECT ... FROM file ...}}, {{file.docx#t1}} or {{file.xlsx!Sheet!A1:C9}}.")
    return out


def _markdown(rows: list[list[str]]) -> str:
    from agent.ingest.parse import table_markdown

    cleaned = [[c.replace("|", "\\|").replace("\n", " ") for c in r] for r in rows]
    return "\n" + table_markdown(cleaned) + "\n"


def _docx_table(path: Path, n: int, ref: str) -> str:
    import docx

    from agent.ingest.parse import _body

    if path.suffix.lower() != ".docx":
        raise DocumentError(f"{ref}: #t{n} names a table of a Word document; {path.name} is not one.")
    tables = [item for kind, item in _body(docx.Document(str(path))) if kind == "t"]
    if not 1 <= n <= len(tables):
        raise DocumentError(f"{ref}: {path.name} has {len(tables)} table(s); there is no t{n}.")
    rows = [[c.text.strip() for c in row.cells] for row in tables[n - 1].rows]
    if not rows:
        raise DocumentError(f"{ref}: table t{n} is empty.")
    return _markdown(rows)


_CELLS = re.compile(r"^([A-Za-z]{1,3})(\d+):([A-Za-z]{1,3})(\d+)$")


def _range(path: Path, spec: str, ref: str) -> str:
    import openpyxl

    from agent.tools.doc_reading import cell_str

    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise DocumentError(f"{ref}: a range names cells of a workbook; {path.name} is not one.")
    sheet, _, cells = spec.rpartition("!")
    if not _CELLS.match(cells.strip()):
        raise DocumentError(f"{ref}: {cells!r} is not a range like A1:C41 (write Sheet!A1:C41 for another sheet).")
    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        if sheet and sheet not in book.sheetnames:
            raise DocumentError(f"{ref}: {path.name} has no sheet {sheet!r}; its sheets: {', '.join(book.sheetnames)}.")
        ws = book[sheet] if sheet else book.worksheets[0]
        rows = [[cell_str(c.value) for c in r] for r in ws[cells.strip().upper()]]   # type: ignore[union-attr]
    finally:
        book.close()
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise DocumentError(f"{ref}: those cells are empty.")
    if len(rows) > MAX_ROWS + 1:
        raise DocumentError(f"{ref}: {len(rows)} rows is more than one document table takes ({MAX_ROWS}).")
    return _markdown(rows)


def _query(path: Path, sql: str, ref: str) -> str:
    from agent.tools.doc_reading import cell_str

    header, rows = _query_rows(path, sql, ref)
    return _markdown([[str(h) for h in header], *[[cell_str(v) for v in r] for r in rows]])


def _query_rows(path: Path, sql: str, ref: str) -> tuple[list[str], list[tuple]]:
    from agent.tools.doc_reading import QueryError, csv_rows, xlsx_rows

    try:
        if path.suffix.lower() == ".csv":
            header, rows = csv_rows(path, sql, limit=MAX_ROWS + 1)
        elif path.suffix.lower() in (".xlsx", ".xlsm"):
            header, rows, _coerced = xlsx_rows(path, sql, limit=MAX_ROWS + 1)
        else:
            raise DocumentError(f"{ref}: sql works on a .xlsx or .csv; {path.name} is neither.")
    except QueryError as exc:
        raise DocumentError(f"{ref}: {exc}") from None
    if len(rows) > MAX_ROWS:
        raise DocumentError(f"{ref}: the query returned more than {MAX_ROWS} rows; narrow it.")
    return header, rows


__all__ = ["MAX_ROWS", "REFERENCE", "expand", "referenced"]
