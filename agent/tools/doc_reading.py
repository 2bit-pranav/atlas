"""read_pdf, read_docx, read_xlsx: fetch from the ingest store, never parse.

The file was parsed at upload (agent/ingest/). These tools find its entry,
wait briefly for pages still in progress, and print blocks: capped near 1,500
tokens, with a header saying what is shown of how much and a footer giving the
exact next call. `search` finds blocks by their words (FTS5), not the phrase.
A file not ingested yet (found in an allowed folder, saved by a script) is
submitted and waited for; the tool policy has checked access before this runs.

The baseline (decisions.md, 2026-11-03) is why each piece is here: the
model answered "not in the document" after reading pages 1-2 of 40, searched
with a whole phrase, and invented a path when the reader was a shell command.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from strands import tool

from agent.ingest.store import PENDING, Store, kind_of
from agent.tools.reading import MAX_CHARS

#: A document this short is shown whole when no pages/section is asked for.
SHORT_PAGES = 5
#: How long a read waits: for the text pass, and for pages being OCR'd.
WAIT_TEXT = 30.0
WAIT_PAGES = 15.0
#: A search covers every page, so it waits longer for OCR to finish. Returning at
#: once, the model searched a 12-page scan 3 s after upload, found nothing, and gave up.
WAIT_SEARCH = 30.0
#: Rows shown when a sheet is read without a range.
SHEET_ROWS = 30
#: Only reads: DuckDB would run DDL and writes, and a read tool must never write.
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|install|load|"
                       r"export|import|call|pragma|set|reset|merge|truncate|checkpoint|vacuum)\b", re.I)
TOOL = {"pdf": "read_pdf", "docx": "read_docx", "xlsx": "read_xlsx"}


def _failed(message: str) -> dict[str, Any]:
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


def parse_pages(spec: str, total: int) -> list[int]:
    """`1-3,7` -> [1, 2, 3, 7], within the document; `all` is every page."""
    if spec.strip().lower() in ("all", "*"):
        return list(range(1, total + 1))
    out: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        try:
            lo, hi = int(a), int(b or a)
        except ValueError:
            continue
        out.update(range(max(1, lo), min(hi, total) + 1))
    return sorted(out)


def _span(pages: list[int]) -> str:
    """[1, 2, 3, 7] -> "1-3, 7"."""
    out: list[str] = []
    for p in pages:
        if out and "-" not in out[-1].split(", ")[-1] and int(out[-1]) == p - 1:
            out[-1] = f"{out[-1]}-{p}"
        elif out and "-" in out[-1] and int(out[-1].split("-")[1]) == p - 1:
            out[-1] = f"{out[-1].split('-')[0]}-{p}"
        else:
            out.append(str(p))
    return ", ".join(out)


def _fit(parts: list[str]) -> tuple[list[str], bool]:
    """As many parts as fit in the budget; a first part longer than it is cut."""
    out, size = [], 0
    for part in parts:
        if out and size + len(part) > MAX_CHARS:
            return out, True
        if not out and len(part) > MAX_CHARS:
            return [part[:MAX_CHARS] + " [... cut]"], True
        out.append(part)
        size += len(part) + 2
    return out, False


def doc_read_tools(store: Store, chat: str, resolve: Callable[[str], Path], workspace: Path,
                   on_taint: Callable[[], None] | None = None) -> list[Any]:
    """The three tools, for one chat."""

    def _open(path: str, kind: str) -> tuple[Path, dict[str, Any]] | dict[str, Any]:
        """The file's ready entry, or an error result."""
        if not path.strip():
            # The model searched without naming the file; with one such file there is no doubt.
            only = [p for p in workspace.glob("*") if p.is_file() and kind_of(p) == kind]
            if len(only) != 1:
                return _failed(f"say which file: path is empty and the workspace has {len(only)} .{kind} files.")
            path = only[0].name
        if kind == "pdf" and path.lower().startswith(("http://", "https://")):
            from skills._shared import LinkError, save_link

            try:
                target, _ = save_link(path, ".pdf", b"%PDF", "PDF", workspace)
            except LinkError as exc:
                return _failed(str(exc))
            if on_taint is not None:
                on_taint()  # a web document can carry instructions, like a web page
        elif "://" in path:
            # file:// would bypass the access check, which reads paths, not links.
            return _failed("give the file's path, not a link (only http(s) links are downloaded)")
        else:
            target = resolve(path)
        actual = kind_of(target)
        if actual != kind:
            other = TOOL.get(actual or "")
            return _failed(f"{target.name} is not a .{kind} file. " + (
                f"Use {other}(path=\"{target.name}\")." if other else
                "Use read_text for text files and read_image for images."))
        if not target.is_file():
            names = sorted(p.name for p in workspace.glob("*") if p.is_file() and not p.name.startswith("."))
            return _failed(f"no file {target.name}. Files in your workspace: {', '.join(names) or 'none'}.")
        sha = store.submit(target, chat)
        e = store.wait(sha, lambda e: e["status"] != "queued", WAIT_TEXT) if sha else None
        if e is None:
            return _failed(f"{target.name} is still being read; try again in a moment.")
        if e["status"] == "failed":
            return _failed(f"{target.name} could not be read: {e['error']}")
        return target, e

    @tool(name="read_pdf")
    def read_pdf(path: str = "", pages: str = "", search: str = "") -> Any:
        """Read a PDF (scanned pages included): by pages, or find something with search.

        A long PDF read without pages shows its outline and first page. To find something,
        search with a few words, e.g. search="invoice number", then read the pages it names.

        Args:
            path: The PDF's file name in your workspace, its full path, or an https link.
            pages: Pages to read, e.g. "3" or "3-5".
            search: Words to find; returns the passages holding them, with their pages.
        """
        got = _open(path, "pdf")
        if isinstance(got, dict):
            return got
        target, e = got
        name, total = target.name, e["pages"]
        sha = e["sha"]
        if search.strip():
            if any(s in PENDING for s in e["page_status"]):
                e = store.wait(sha, lambda e: not any(s in PENDING for s in e["page_status"]), WAIT_SEARCH) or e
            hits = store.search(sha, search)
            pending = [i + 1 for i, s in enumerate(e["page_status"]) if s in PENDING]
            note = (f"\nPages {_span(pending)} are still being read (OCR); search again shortly to include them."
                    if pending else "")
            if not hits:
                return f"No passage in {name} ({total} pages) holds any of: {search}.{note}"
            parts, cut = _fit([f"--- page {b['page']} ---\n{b['text']}" for b in hits])
            found = sorted({b["page"] for b in hits})
            return (f"{name}: {len(hits)} passages match \"{search}\", on pages {_span(found)}; best first"
                    + (f", showing {len(parts)}" if cut else "") + f". Read a whole page with "
                    f"read_pdf(path=\"{name}\", pages=\"N\").{note}\n\n" + "\n\n".join(parts))

        if pages.strip():
            wanted = parse_pages(pages, total)
            if not wanted:
                return _failed(f"no pages in {pages!r}; {name} has {total} pages.")
        else:
            wanted = list(range(1, total + 1)) if total <= SHORT_PAGES else [1]
        store.want(sha, wanted)
        e = store.wait(sha, lambda e: all(e["page_status"][p - 1] not in PENDING for p in wanted),
                       WAIT_PAGES) or e
        status = e["page_status"]
        by_page: dict[int, list[str]] = {}
        for b in store.blocks(sha, wanted):
            by_page.setdefault(b["page"], []).append(b["text"])
        parts = []
        for p in wanted:
            s = status[p - 1]
            title = f"--- page {p} of {total}" + (" (scanned, read by OCR)" if s == "ocr" else "") + " ---"
            body = ("[still being read by OCR; read this page again shortly]" if s in PENDING
                    else "\n\n".join(by_page.get(p, [])) or "[no text on this page]")
            parts.append(f"{title}\n{body}")
        shown, cut = _fit(parts)
        last = wanted[len(shown) - 1]
        head = f"{name}: page{'s' * (len(shown) > 1)} {_span(wanted[:len(shown)])} of {total}"
        if last < total or cut:
            # Search first: offered pages first, the model walked 18 pages of 40 and gave up.
            head += (f". The other {total - len(shown)} pages are NOT shown; do not conclude something is absent. "
                     f"To find something, search: read_pdf(path=\"{name}\", search=\"a few words\"). "
                     f"To read on: pages=\"{last + 1}-{min(total, last + 2)}\"")
        outline = ""
        if not pages.strip() and total > SHORT_PAGES and e["outline"]:
            outline = "Outline:\n" + "\n".join(f"{'  ' * (o['level'] - 1)}{o['title']} (page {o['page']})"
                                               for o in e["outline"][:40]) + "\n\n"
        ocr = any(status[p - 1] == "ocr" for p in wanted)
        return (head + ("\nOCR text can have recognition errors; quote numbers and names as printed." if ocr else "")
                + "\n\n" + outline + "\n\n".join(shown))

    @tool(name="read_docx")
    def read_docx(path: str = "", section: str = "", search: str = "") -> Any:
        """Read a Word document (.docx): by section number from its outline, or find something with search.

        Each paragraph shows its id ([b12]); a table shows its id (t1) and the form of a cell's (t1.r2.c3).
        A long document read without section shows its outline and first section.

        Args:
            path: The document's file name in your workspace, or its full path.
            section: A section number from the outline, e.g. "3" or "3.2".
            search: Words to find; returns the paragraphs and tables holding them.
        """
        got = _open(path, "docx")
        if isinstance(got, dict):
            return got
        target, e = got
        name, sha = target.name, e["sha"]
        blocks = store.blocks(sha)
        outline = e["outline"] or []
        if search.strip():
            hits = store.search(sha, search)
            if not hits:
                return f"No paragraph or table in {name} holds any of: {search}."
            parts, cut = _fit([_docx_block(b) for b in hits])
            return (f"{name}: {len(hits)} blocks match \"{search}\", best first"
                    + (f", showing {len(parts)}" if cut else "") + ".\n\n" + "\n\n".join(parts))
        if section.strip():
            s = section.strip().rstrip(".")
            chosen = [b for b in blocks if (b["section"] or "") == s or (b["section"] or "").startswith(s + ".")]
            if not chosen:
                known = ", ".join(o["section"] for o in outline) or "none (no headings)"
                return _failed(f"no section {s!r} in {name}. Sections: {known}.")
            head = f"{name}: section {s}"
        else:
            chosen, head = blocks, f"{name}"
        parts, cut = _fit([_docx_block(b) for b in chosen])
        if cut and not section.strip() and outline:
            first = outline[0]["section"].split(".")[0]
            body = [b for b in blocks if (b["section"] or "") in ("", first) or (b["section"] or "").startswith(first + ".")]
            parts, _ = _fit([_docx_block(b) for b in body])
            toc = "\n".join(f"{'  ' * o['section'].count('.')}{o['section']} {o['title']}" for o in outline[:60])
            return (f"{name}: {len(blocks)} blocks, too long to show at once; outline, then section {first}. "
                    f"Read a section with read_docx(path=\"{name}\", section=\"2\"), or find something with "
                    f"read_docx(path=\"{name}\", search=\"words\").\n\nOutline:\n{toc}\n\n" + "\n\n".join(parts))
        if cut:
            head += (f": the first {len(parts)} of {len(chosen)} blocks; the rest are NOT shown. Find something "
                     f"with read_docx(path=\"{name}\", search=\"words\")")
        return head + "\n\n" + "\n\n".join(parts)

    @tool(name="read_xlsx")
    def read_xlsx(path: str = "", sheet: str = "", range: str = "", sql: str = "") -> Any:  # noqa: A002
        """Read an Excel workbook (.xlsx): its sheets, a sheet's rows, a range, or a SQL query.

        No arguments lists the sheets and shows the first rows. For totals and counts use sql, with
        the sheet as the table and its first row as column names, e.g.
        sql='SELECT SUM("revenue") FROM "Mar"'. Text values go in single quotes: WHERE "region" = 'North'.

        Args:
            path: The workbook's file name in your workspace, or its full path.
            sheet: A sheet's name.
            range: Cells to show, e.g. "A1:D20" or "Mar!A1:D20".
            sql: One SELECT query over the sheets.
        """
        got = _open(path, "xlsx")
        if isinstance(got, dict):
            return got
        target, e = got
        name = target.name
        sheets = (e["info"] or {}).get("sheets") or []
        names = [s["name"] for s in sheets]
        listing = "Sheets: " + "; ".join(f"{s['name']} ({s['rows']} rows x {s['cols']} cols)" for s in sheets)
        if sql.strip():
            return _query(target, sql, names, sheet)
        if "!" in range:
            sheet, range = range.split("!", 1)
            sheet = sheet.strip("'\"")
        target_sheet = sheet or (names[0] if names else "")
        if target_sheet not in names:
            return _failed(f"no sheet {sheet!r} in {name}. {listing}.")
        return f"{name}: {listing}.\n\n" + _grid(target, target_sheet, range)

    return [read_pdf, read_docx, read_xlsx]


def _docx_block(b: dict[str, Any]) -> str:
    if b["kind"] == "heading":
        number = f"{b['section']} " if b["section"] else ""
        return f"{'#' * min(6, b.get('level') or 1)} {number}{b['text']} [{b['id']}]"
    if b["kind"] == "table":
        # Rows numbered as edit_docx counts them, so a cell's id is read off, not worked out:
        # shown as a pipe row, the model passed the whole row to the edit tool (2026-11-03).
        lines = [ln for i, ln in enumerate(b["text"].splitlines()) if i != 1]   # drop |---|
        rows = "\n".join(f"r{n}: {ln.strip().strip('|').strip()}" for n, ln in enumerate(lines, 1))
        return (f"[{b['id']}: table, {b.get('rows')} rows x {b.get('cols')} cols. A cell is "
                f"{b['id']}.rROW.cCOL, columns counted from the left: c1, c2, ...]\n{rows}")
    if b["kind"] == "image":
        return b["text"]
    return f"[{b['id']}] {b['text']}"


def _cells(spec: str) -> tuple[int, int, int, int] | None:
    """"B2:D20" -> (min_col, min_row, max_col, max_row)."""
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d+)(?::([A-Za-z]{1,3})(\d+))?", spec.strip())
    if not m:
        return None

    def col(letters: str) -> int:
        n = 0
        for ch in letters.upper():
            n = n * 26 + ord(ch) - 64
        return n

    c1, r1 = col(m[1]), int(m[2])
    c2, r2 = (col(m[3]), int(m[4])) if m[3] else (c1, r1)
    return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def _grid(path: Path, sheet: str, spec: str) -> str:
    """A sheet's cells with their row numbers and column letters, capped."""
    import openpyxl

    from agent.ingest.parse import cell_text, column

    bounds = _cells(spec) if spec.strip() else None
    if spec.strip() and bounds is None:
        return f"Error: {spec!r} is not a range like A1:D20."
    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = book[sheet]
        c1, r1, c2, r2 = bounds or (1, 1, ws.max_column or 1, min(ws.max_row or 1, SHEET_ROWS + 1))
        rows = list(ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True))
        total_rows = ws.max_row or 0
    finally:
        book.close()
    lines = ["row | " + " | ".join(column(c) for c in range(c1, c2 + 1))]
    lines += [f"{r1 + i} | " + " | ".join(cell_text(v) for v in row) for i, row in enumerate(rows)]
    shown, cut = _fit(lines)
    last = r1 + len(shown) - 2
    out = f"Sheet {sheet}, rows {r1}-{last} of {total_rows}:\n" + "\n".join(shown)
    if last < (r2 if bounds else total_rows):
        out += (f"\n[rows after {last} are NOT shown. Next: range=\"{sheet}!{column(c1)}{last + 1}:"
                f"{column(c2)}{last + SHEET_ROWS}\", or use sql for totals]")
    return out


def _query(path: Path, sql: str, names: list[str], sheet: str = "") -> Any:
    """One SELECT over the workbook's sheets, each loaded as a table (first row = column names).

    A bare expression with a sheet (`SUM("revenue")`, sheet Mar) is completed to
    `SELECT ... FROM "Mar"`: the model wrote the expression and stopped there.
    """
    import duckdb
    import openpyxl

    if sheet and not re.match(r"\s*(select|with)\b", sql, re.I):
        sql = f'SELECT {sql} FROM "' + sheet.replace('"', '""') + '"'

    if FORBIDDEN.search(sql) or ";" in sql.strip().rstrip(";"):
        return _failed("only one SELECT query is allowed.")
    con = duckdb.connect(":memory:")
    coerced = 0
    columns: dict[str, list[str]] = {}
    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        for ws in book.worksheets:
            rows = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
            if not rows:
                continue
            seen: dict[str, int] = {}
            cols = []
            for i, c in enumerate(rows[0]):
                c = str(c).strip() if c is not None else f"column_{i + 1}"
                seen[c] = seen.get(c, -1) + 1
                cols.append(f"{c}_{seen[c]}" if seen[c] else c)
            columns[ws.title] = cols
            body = [tuple(r) + (None,) * (len(cols) - len(r)) for r in rows[1:]]
            numeric = [_numeric([r[i] for r in body]) for i in range(len(cols))]
            coerced += sum(1 for r in body for i, n in enumerate(numeric)
                           if n and r[i] is not None and not isinstance(r[i], int | float))
            q = '"' + ws.title.replace('"', '""') + '"'
            con.execute(f"CREATE TABLE {q} (" + ", ".join(
                '"' + c.replace('"', '""') + '" ' + ("DOUBLE" if n else "VARCHAR") for c, n in zip(cols, numeric, strict=True)) + ")")
            data = [tuple(_value(r[i], numeric[i]) for i in range(len(cols))) for r in body]
            if data:
                con.executemany(f"INSERT INTO {q} VALUES ({', '.join('?' * len(cols))})", data)
        cur = con.execute(sql)
        header = [d[0] for d in cur.description or []]
        result = cur.fetchmany(200)
    except duckdb.Error as exc:
        msg = str(exc).split("\n")[0]
        hint = (" Text values go in single quotes ('North'); double quotes name a column or sheet."
                if "column" in msg.lower() and '"' in sql else "")
        tables = "; ".join(f'"{t}" columns: ' + ", ".join(f'"{c}"' for c in cs) for t, cs in columns.items())
        return _failed(f"the query failed: {msg}.{hint} Tables (sheets) and their columns: {tables}. "
                       'Columns are named by the header row, not by letter.')
    finally:
        book.close()
        con.close()
    lines = [" | ".join(header)] + [" | ".join(cell_str(v) for v in r) for r in result]
    shown, cut = _fit(lines)
    # A total that silently skipped "n/a" cells is a confidently wrong number: say so.
    note = (f"\nNote: {coerced} cell{'s' * (coerced != 1)} in number columns held text (like \"n/a\") "
            "and counted as empty." if coerced else "")
    return (f"{len(result)} row{'s' * (len(result) != 1)}" + (f", showing {len(shown) - 1}" if cut else "")
            + ":\n" + "\n".join(shown) + note)


def _numeric(values: list[Any]) -> bool:
    """A number column: at least 90% of its filled cells are numbers (real files carry "n/a")."""
    filled = [v for v in values if v is not None]
    return bool(filled) and sum(isinstance(v, int | float) for v in filled) >= 0.9 * len(filled)


def _value(v: Any, numeric: bool) -> Any:
    if numeric:
        return v if isinstance(v, int | float) else None   # "n/a" in a number column is NULL
    return None if v is None else str(v)


def cell_str(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "" if v is None else str(v)


__all__ = ["doc_read_tools", "parse_pages"]
