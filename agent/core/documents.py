"""Creating and editing documents: Markdown in, a valid file out.

The model writes **Markdown**, which a small model writes reliably, and these
converters turn it into docx, pdf or xlsx. Hand-written JSON piped through
`echo '...' |` broke on the first apostrophe and on any slip in nesting, and
the model then wrote plain text into a `.docx` -- a corrupt file.

Three guarantees:

1. **Never a corrupt file.** Each document is written to a temporary file,
   reopened with its own library to prove it parses, and only then moved into
   place. A failure leaves the previous version untouched.
2. **One precise error.** A failure says what was wrong in words the model can
   act on ("an xlsx needs a Markdown table"), not a traceback.
3. **Binary files are only written through these tools.** The tool policy
   (`policy.py`) refuses the plain `write`/`edit` tools on .docx/.xlsx/.pdf/.pptx.

Supported Markdown: headings, paragraphs, **bold**, *italic*, `code`, links,
bullet and numbered lists (nested), tables, fenced code, block quotes,
horizontal rules and images (`![caption](path)`). The pdf and docx readers
save a document's images and print them in that form, so rewriting a document
keeps its figures: the model copies the lines across.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from markdown_it import MarkdownIt
from strands import tool

#: Formats `create_document` builds from Markdown. Text formats are written as is.
BINARY = {".docx", ".pdf", ".xlsx"}
TEXT = {".md", ".txt", ".csv", ".json", ".html"}
#: Never written with the plain write/edit tools.
GUARDED = BINARY | {".pptx", ".doc", ".xls"}


class DocumentError(Exception):
    """Shown to the model verbatim, so it says what to change."""


# ------------------------------------------------------------- parsing --


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: str | None = None


@dataclass
class Block:
    kind: str                       # heading | para | item | table | code | quote | hr | image
    runs: list[Run] = field(default_factory=list)
    level: int = 0                  # heading level, or list nesting depth
    ordered: bool = False
    number: int = 0
    rows: list[list[list[Run]]] = field(default_factory=list)  # table: first row is the header
    text: str = ""                  # code; image: the path as written
    group: int = 0                  # list items: which top-level list they belong to


def _images(token: Any) -> list[Block]:
    """`![alt](src)` inside a paragraph, as image blocks in order."""
    return [Block("image", [Run(c.content or "")], text=c.attrGet("src") or "")
            for c in token.children or [] if c.type == "image" and c.attrGet("src")]


def _inline(token: Any) -> list[Run]:
    runs: list[Run] = []
    bold = italic = False
    link: str | None = None
    for child in token.children or []:
        t = child.type
        if t == "strong_open":
            bold = True
        elif t == "strong_close":
            bold = False
        elif t == "em_open":
            italic = True
        elif t == "em_close":
            italic = False
        elif t == "link_open":
            link = child.attrGet("href")
        elif t == "link_close":
            link = None
        elif t == "code_inline":
            runs.append(Run(child.content, bold, italic, True, link))
        elif t in ("softbreak", "hardbreak"):
            runs.append(Run("\n" if t == "hardbreak" else " ", bold, italic, False, link))
        elif t == "text" and child.content:
            runs.append(Run(child.content, bold, italic, False, link))
    return runs


def parse_markdown(text: str) -> list[Block]:
    md = MarkdownIt("commonmark").enable("table").enable("strikethrough")
    tokens = md.parse(text)
    blocks: list[Block] = []
    lists: list[dict[str, Any]] = []      # stack of {"ordered", "n"}
    quote = 0
    table: Block | None = None
    row: list[list[Run]] | None = None
    in_item_para = False
    group = 0

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "heading_open":
            blocks.append(Block("heading", _inline(tokens[i + 1]), level=int(tok.tag[1])))
            i += 3
            continue
        if t in ("bullet_list_open", "ordered_list_open"):
            start = int(tok.attrGet("start") or 1)
            if not lists:
                group += 1
            lists.append({"ordered": t == "ordered_list_open", "n": start - 1})
        elif t in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif t == "list_item_open":
            lists[-1]["n"] += 1
            in_item_para = True
        elif t == "paragraph_open":
            runs = _inline(tokens[i + 1])
            images = _images(tokens[i + 1])
            if images and not plain(runs).strip():
                # A paragraph that is only an image: the image is the block.
                blocks.extend(images)
                in_item_para = False
                i += 3
                continue
            if lists and in_item_para:
                blocks.append(Block("item", runs, level=len(lists) - 1, group=group,
                                    ordered=lists[-1]["ordered"], number=lists[-1]["n"]))
                in_item_para = False
            else:
                blocks.append(Block("quote" if quote else "para", runs))
            blocks.extend(images)
            i += 3
            continue
        elif t == "blockquote_open":
            quote += 1
        elif t == "blockquote_close":
            quote -= 1
        elif t in ("fence", "code_block"):
            blocks.append(Block("code", text=tok.content.rstrip("\n")))
        elif t == "hr":
            blocks.append(Block("hr"))
        elif t == "table_open":
            table = Block("table")
        elif t == "tr_open":
            row = []
        elif t in ("th_open", "td_open"):
            row.append(_inline(tokens[i + 1]))  # type: ignore[union-attr]
            i += 3
            continue
        elif t == "tr_close" and table is not None and row is not None:
            table.rows.append(row)
            row = None
        elif t == "table_close" and table is not None:
            blocks.append(table)
            table = None
        i += 1
    return blocks


def plain(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


# --------------------------------------------------------------- docx --


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def _resolve_images(blocks: list[Block], base: Path | None) -> list[str]:
    """Point every image block at a real file. Returns the ones that are missing."""
    from agent.core.shell_env import windows_path

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


# ---------------------------------------------------------------- pdf --

_FONTS: dict[str, str] | None = None


def _pdf_fonts() -> dict[str, str]:
    """A Unicode TrueType font if Windows has one; Helvetica draws '→' as a box."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    _FONTS = {"body": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique",
              "bolditalic": "Helvetica-BoldOblique", "mono": "Courier"}
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    faces = {"body": "segoeui.ttf", "bold": "segoeuib.ttf", "italic": "segoeuii.ttf",
             "bolditalic": "segoeuiz.ttf", "mono": "consola.ttf", "symbol": "seguisym.ttf"}
    try:
        if all((fonts / f).is_file() for f in faces.values()):
            for key, file in faces.items():
                pdfmetrics.registerFont(TTFont(f"Atlas-{key}", str(fonts / file)))
            pdfmetrics.registerFontFamily("Atlas-body", normal="Atlas-body", bold="Atlas-bold",
                                          italic="Atlas-italic", boldItalic="Atlas-bolditalic")
            _FONTS = {k: f"Atlas-{k}" for k in faces}
    except Exception:  # noqa: BLE001 - fall back to the built-in fonts
        pass
    return _FONTS


def _with_fallback(text: str) -> str:
    """Escape `text`, drawing characters the body font lacks (✓, ★) with the symbol font."""
    from xml.sax.saxutils import escape

    fonts = _pdf_fonts()
    if "symbol" not in fonts:
        return escape(text)
    from reportlab.pdfbase import pdfmetrics

    body = pdfmetrics.getFont(fonts["body"]).face
    symbol = pdfmetrics.getFont(fonts["symbol"]).face
    out = []
    for ch in text:
        code = ord(ch)
        if code > 0x7F and code not in body.charToGlyph and code in symbol.charToGlyph:
            out.append(f'<font face="{fonts["symbol"]}">{escape(ch)}</font>')
        else:
            out.append(escape(ch))
    return "".join(out)


def _markup(runs: list[Run], mono: str) -> str:
    from xml.sax.saxutils import escape

    out = []
    for r in runs:
        text = _with_fallback(r.text).replace("\n", "<br/>")
        if r.code:
            text = f'<font face="{mono}">{text}</font>'
        if r.bold:
            text = f"<b>{text}</b>"
        if r.italic:
            text = f"<i>{text}</i>"
        if r.link:
            text = f'<link href="{escape(r.link)}" color="blue">{text}</link>'
        out.append(text)
    return "".join(out)


def _write_pdf(blocks: list[Block], path: Path, title: str | None) -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, ListFlowable, ListItem, Paragraph,
                                    Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

    f = _pdf_fonts()
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName=f["body"], fontSize=10.5, leading=15)
    heads = {n: ParagraphStyle(f"h{n}", parent=base[f"Heading{min(n, 6)}"], fontName=f["bold"])
             for n in range(1, 7)}
    quote = ParagraphStyle("quote", parent=body, leftIndent=12, textColor=colors.HexColor("#555555"))
    code = ParagraphStyle("code", parent=body, fontName=f["mono"], fontSize=9, leading=12,
                          backColor=colors.HexColor("#f4f4f4"), borderPadding=4)
    cell = ParagraphStyle("cell", parent=body, fontSize=9.5, leading=12)

    from reportlab.platypus import Image as PdfImage

    story: list[Any] = []
    counts = {"headings": 0, "paragraphs": 0, "list_items": 0, "tables": 0, "images": 0}
    max_w, max_h = A4[0] - 40 * mm, A4[1] - 60 * mm
    caption = ParagraphStyle("caption", parent=body, fontSize=9, textColor=colors.HexColor("#666666"),
                             fontName=f["italic"])
    pending: list[Block] = []

    def flush_list() -> None:
        if not pending:
            return
        items = [ListItem(Paragraph(_markup(b.runs, f["mono"]), body), leftIndent=12 + 12 * b.level)
                 for b in pending]
        ordered = pending[0].ordered
        story.append(ListFlowable(items, bulletType="1" if ordered else "bullet",
                                  start=pending[0].number if ordered else None,
                                  bulletFontName=f["body"]))
        pending.clear()

    for b in blocks:
        # A new list (or a switch between bullets and numbers) starts its own flowable.
        if b.kind != "item" or (pending and (b.group != pending[0].group or
                                             (b.level == 0 and b.ordered != pending[0].ordered))):
            flush_list()
        if b.kind == "image":
            w, h = _image_size(Path(b.text))
            scale = min(1.0, max_w / w, max_h / h)
            story.append(PdfImage(b.text, width=w * scale, height=h * scale, hAlign="CENTER"))
            if plain(b.runs).strip():
                story.append(Paragraph(_markup(b.runs, f["mono"]), caption))
            counts["images"] += 1
        elif b.kind == "heading":
            story.append(Paragraph(_markup(b.runs, f["mono"]), heads[min(b.level, 6)]))
            counts["headings"] += 1
        elif b.kind == "para":
            story.append(Paragraph(_markup(b.runs, f["mono"]), body))
            counts["paragraphs"] += 1
        elif b.kind == "quote":
            story.append(Paragraph(_markup(b.runs, f["mono"]), quote))
        elif b.kind == "item":
            pending.append(b)
            counts["list_items"] += 1
        elif b.kind == "code":
            story.append(Preformatted(b.text, code))
        elif b.kind == "hr":
            story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc")))
        elif b.kind == "table" and b.rows:
            width = max(len(r) for r in b.rows)
            data = [[Paragraph(_markup(r[c] if c < len(r) else [], f["mono"]), cell) for c in range(width)]
                    for r in b.rows]
            t = Table(data, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("FONTNAME", (0, 0), (-1, 0), f["bold"]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t)
            counts["tables"] += 1
        story.append(Spacer(1, 4))
    flush_list()
    if not story:
        raise DocumentError("the Markdown has no content to put in the PDF")
    SimpleDocTemplate(str(path), pagesize=A4, title=title or path.stem,
                      leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=18 * mm).build(story)
    return counts


def _check_pdf(path: Path) -> None:
    data = path.read_bytes()
    if not data.startswith(b"%PDF") or b"%%EOF" not in data[-1024:]:
        raise DocumentError("the PDF did not come out complete")


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


def create(path: Path, content: str, title: str | None = None,
           base: Path | None = None) -> dict[str, Any]:
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
    missing = _resolve_images(blocks, base or path.parent)
    if ext == ".docx":
        info = _atomic(path, lambda p: _write_docx(blocks, p, title), _check_docx)
        return {**info, "missing_images": missing}
    if ext == ".pdf":
        info = _atomic(path, lambda p: _write_pdf(blocks, p, title), _check_pdf)
        return {**info, "missing_images": missing}
    return _atomic(path, lambda p: _write_xlsx(blocks, p, title, content), _check_xlsx)


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


def _require(n: int, replace_all: bool, find: str, lines: list[str]) -> None:
    if n == 0:
        words = [w for w in re.findall(r"\w{4,}", find)][:3]
        near = [ln.strip() for ln in lines if any(w.lower() in ln.lower() for w in words)][:3]
        hint = (" Lines with similar words: " + " | ".join(f'"{n[:80]}"' for n in near)) if near else ""
        raise DocumentError(f'"{find[:80]}" is not in the document. `find` must match the '
                            f"text exactly, within one paragraph or cell.{hint}")
    if n > 1 and not replace_all:
        raise DocumentError(f'"{find[:80]}" appears {n} times. Give more surrounding text so '
                            "it is unique, or set replace_all to true.")


def _docx_paragraphs(doc: Any) -> list[Any]:
    out = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for c in row.cells:
                out.extend(c.paragraphs)
    return out


def _edit_docx(src: Path, dst: Path, find: str, replace: str, replace_all: bool) -> int:
    from docx import Document

    doc = Document(str(src))
    paragraphs = _docx_paragraphs(doc)
    n = sum(p.text.count(find) for p in paragraphs)
    _require(n, replace_all, find, [p.text for p in paragraphs])
    done = 0
    for p in paragraphs:
        if find not in p.text or (done and not replace_all):
            continue
        runs = p.runs
        # Within one run: keep every run's formatting untouched.
        hit = next((r for r in runs if find in r.text), None)
        if hit is not None:
            hit.text = hit.text.replace(find, replace, -1 if replace_all else 1)
        else:
            # Spans runs: the paragraph's text goes into its first run.
            new = p.text.replace(find, replace, -1 if replace_all else 1)
            runs[0].text = new
            for r in runs[1:]:
                r.text = ""
        done += 1
        if not replace_all:
            break
    doc.save(str(dst))
    return n if replace_all else 1


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


# --------------------------------------------------------------- tools --


def _failed(message: str) -> dict[str, Any]:
    """An error result, so the failure counts as one (resilience.py nudges on it)."""
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


def document_tools(workspace: Path, shown: Callable[[Path], str]) -> list[Any]:
    """The two agent tools, bound to one chat's workspace.

    `shown` turns a path into the form the model is shown (`model_path`).
    """
    from agent.core.shell_env import windows_path

    def resolve(path: str) -> Path:
        p = Path(windows_path(path)) if path.startswith("/") else Path(path)
        return p if p.is_absolute() else workspace / p

    @tool(name="create_document")
    def create_document(path: str, content: str, title: str = "") -> Any:
        """Create a Word (.docx), PDF (.pdf) or Excel (.xlsx) file from Markdown. Also .md/.txt/.csv.

        Write the whole document as Markdown in `content`: # headings, paragraphs,
        **bold**, *italic*, - bullets, 1. numbered lists, tables
        (| Name | Total |, then |---|---|, then one row per line), and images
        as ![caption](path) on their own line -- to keep a source document's
        images, copy the ![...](...) lines its reader printed. For .xlsx,
        every Markdown table becomes a sheet named after the heading above it.
        An existing file at `path` is replaced. Use this, never `write`, for
        .docx/.pdf/.xlsx files.

        Args:
            path: File name (saved in your workspace) or a full path, ending in .docx, .pdf or .xlsx.
            content: The document, as Markdown.
            title: Optional document title.
        """
        target = resolve(path)
        try:
            info = create(target, content, title or None, base=workspace)
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001 - the model needs words, not a traceback
            return _failed(f"could not create {target.name}: {type(exc).__name__}: {exc}")
        missing = info.pop("missing_images", [])
        detail = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in info.items() if v)
        size = target.stat().st_size
        note = (f" These images were not found and were left out: {', '.join(missing)}. "
                "Use the exact image paths the reader printed." if missing else "")
        return (f"Created {shown(target)} ({size:,} bytes{'; ' + detail if detail else ''}).{note} "
                "The user sees it as a download in the chat; tell them it is ready.")

    @tool(name="edit_document")
    def edit_document(path: str, find: str, replace: str, replace_all: bool = False) -> Any:
        """Change text inside an existing .docx, .xlsx, .md or .txt file, keeping everything else.

        `find` must match the document's text exactly, within one paragraph or one
        cell. Read the document first (with its skill) to copy the exact text.

        Args:
            path: The document's file name in your workspace, or its full path.
            find: The exact text to replace.
            replace: The new text. Empty to delete.
            replace_all: Replace every occurrence instead of exactly one.
        """
        target = resolve(path)
        try:
            n = edit(target, find, replace, replace_all)
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _failed(f"could not edit {target.name}: {type(exc).__name__}: {exc}")
        return f"Edited {shown(target)}: replaced {n} occurrence{'s' if n != 1 else ''}."

    return [create_document, edit_document]


__all__ = ["DocumentError", "GUARDED", "create", "document_tools", "edit", "parse_markdown"]
