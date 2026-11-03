"""A file into ordered blocks: what the read tools fetch and the edit tools address.

A block is a dict: `id`, `kind` (heading, para, table, image, rows), `text`,
`page` (PDFs), `section` (the numbered outline path, docx). Ids per format:

    pdf    p27.3          page 27, block 3 (PDFs are rebuilt, never edited in place)
    docx   b12, t1        body paragraph 12, table 1 (a cell is t1.r3.c3)
    xlsx   Mar!A1:C51     a run of rows, the header repeated in each block

Images are saved under the entry's folder and printed as
`![caption](asset:<sha12>/<file>)`, which `create_document` resolves for a
chat that owns the file (store.py), so nothing is written beside the user's
file and no `.data` path is shown to the model.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent.ingest import ocr

#: Bumped when blocks change shape, so stored entries are parsed again.
PARSER = 1
#: A paragraph longer than this is split at line ends.
MAX_BLOCK = 1200
#: Images smaller than this on both sides are icons and rules, not figures.
MIN_IMAGE_PX = 64
#: Per document: a brochure with 200 thumbnails would flood every read.
MAX_IMAGES = 30
#: Rows per spreadsheet block.
XLSX_ROWS = 50

Block = dict[str, Any]


def _split(text: str) -> list[str]:
    """Paragraphs (blank-line separated), long ones cut at line ends."""
    out: list[str] = []
    for para in "\n".join(line.rstrip() for line in text.replace("\r", "").split("\n")).split("\n\n"):
        para = para.strip()
        while len(para) > MAX_BLOCK:
            cut = para.rfind("\n", 0, MAX_BLOCK)
            cut = cut if cut > MAX_BLOCK // 3 else MAX_BLOCK
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def image_line(sha: str, name: str, caption: str) -> str:
    return f"![{caption}](asset:{sha[:12]}/{name})"


# -------------------------------------------------------------------- pdf --


def pdf_open(path: Path) -> Any:
    import pypdfium2 as pdfium

    return pdfium.PdfDocument(str(path))


def pdf_outline(doc: Any) -> list[dict[str, Any]]:
    out = []
    try:
        for item in doc.get_toc():
            if item.page_index is not None:
                out.append({"level": item.level + 1, "title": item.title, "page": item.page_index + 1})
    except Exception:  # noqa: BLE001 - a broken outline is no outline
        return []
    return out


def pdf_page(doc: Any, index: int, sha: str, assets: Path, budget: list[int]) -> tuple[str, list[Block]]:
    """One page from its text layer: (status, blocks).

    Status: `text`, `scan` (needs OCR of the page), `pictures` (text done; large
    pictures to read) or `blank`.
    """
    page = doc[index]
    text = page.get_textpage().get_text_range()
    n = index + 1
    if ocr.is_scanned(page, text):
        return "scan", []
    blocks = [{"id": f"p{n}.{i}", "kind": "para", "text": t, "page": n}
              for i, t in enumerate(_split(text), 1)]
    blocks += _pdf_images(page, n, sha, assets, budget, len(blocks))
    big = any(share >= ocr.PICTURE_MIN_AREA for _, _, share in ocr.pictures(page))
    if not blocks:
        return "blank", []
    return ("pictures" if big else "text"), blocks


def pdf_ocr(doc: Any, index: int, status: str, sha: str, assets: Path, budget: list[int],
            blocks: list[Block]) -> tuple[str, list[Block]]:
    """Finish a page the text pass left pending: OCR the scan, or its pictures."""
    page = doc[index]
    n = index + 1
    if status == "pictures":
        extra = ocr.picture_text(page)
        start = len(blocks)
        return "text", blocks + [{"id": f"p{n}.{start + i}", "kind": "para", "text": t, "page": n}
                                 for i, t in enumerate(extra, 1)]
    text, score = ocr.read_image(ocr.render_page(page))
    out = [{"id": f"p{n}.{i}", "kind": "para", "text": t, "page": n, "conf": round(score, 2)}
           for i, t in enumerate(_split(text), 1)]
    # The page-sized image is the scan itself: its text is above, not an image to keep.
    out += _pdf_images(page, n, sha, assets, budget, len(out), skip_page_sized=True)
    return ("ocr" if out else "blank"), out


def _pdf_images(page: Any, n: int, sha: str, assets: Path, budget: list[int], start: int,
                skip_page_sized: bool = False) -> list[Block]:
    out = []
    for k, obj, share in ocr.pictures(page):
        if budget[0] <= 0 or (skip_page_sized and share >= ocr.PAGE_SIZED):
            continue
        try:
            w, h = obj.get_px_size()
            if w < MIN_IMAGE_PX and h < MIN_IMAGE_PX:
                continue
            name = f"p{n}-{k}.png"
            assets.mkdir(parents=True, exist_ok=True)
            ocr.bitmap(obj).save(assets / name)
        except Exception:  # noqa: BLE001 - one odd image must not lose the page
            continue
        budget[0] -= 1
        out.append({"id": f"p{n}.{start + len(out) + 1}", "kind": "image", "page": n,
                    "text": image_line(sha, name, f"page {n}, image {k}")})
    return out


# ------------------------------------------------------------------- docx --


BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def _body(document: Any) -> Iterator[tuple[str, Any]]:
    """Paragraphs and tables in document order (python-docx lists them apart)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield "p", Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield "t", Table(child, document)


def _level(paragraph: Any) -> int:
    """A heading's level (Heading 2 is 2), or 0. A Title is the document's name, not a section."""
    name = (paragraph.style.name or "") if paragraph.style is not None else ""
    if name.startswith("Heading "):
        try:
            return max(1, int(name.split()[1]))
        except ValueError:
            return 0
    return 0


def table_markdown(rows: list[list[str]]) -> str:
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, *rest = rows
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * width) + "|"]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rest])


def docx_blocks(path: Path, sha: str, assets: Path) -> tuple[list[Block], list[dict[str, Any]]]:
    """(blocks, outline). Paragraph ids count every body paragraph, empty ones
    too, so `b12` is the 12th `w:p` in the body: what an in-place edit finds."""
    import docx

    document = docx.Document(str(path))
    blocks: list[Block] = []
    outline: list[dict[str, Any]] = []
    counters: list[int] = []
    section = ""
    p_no = t_no = images = 0
    for kind, item in _body(document):
        if kind == "t":
            t_no += 1
            rows = [[c.text.strip().replace("\n", " ") for c in row.cells] for row in item.rows]
            if rows:
                blocks.append({"id": f"t{t_no}", "kind": "table", "section": section,
                               "text": table_markdown(rows), "rows": len(rows), "cols": max(map(len, rows))})
            continue
        p_no += 1
        text = item.text.strip()
        level = _level(item) if text else 0
        if text and item.style is not None and item.style.name == "Title":
            blocks.append({"id": f"b{p_no}", "kind": "heading", "level": 1, "section": "", "text": text})
        elif level:
            counters = (counters + [0] * level)[:level]
            counters[-1] += 1
            section = ".".join(map(str, counters))
            outline.append({"section": section, "title": text, "block": f"b{p_no}"})
            blocks.append({"id": f"b{p_no}", "kind": "heading", "level": level, "section": section, "text": text})
        elif text:
            blocks.append({"id": f"b{p_no}", "kind": "para", "section": section, "text": text})
        for blip in item._p.iter(BLIP):
            if images >= MAX_IMAGES:
                break
            rid = blip.get(EMBED)
            part = document.part.related_parts.get(rid) if rid else None
            ext = Path(getattr(part, "partname", "x.png")).suffix.lower() if part is not None else ""
            if part is None or ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp") or not part.blob:
                continue  # EMF/WMF: a rewritten document may not draw them
            images += 1
            name = f"image{images}{ext}"
            assets.mkdir(parents=True, exist_ok=True)
            (assets / name).write_bytes(part.blob)
            blocks.append({"id": f"b{p_no}.img{images}", "kind": "image", "section": section,
                           "text": image_line(sha, name, f"image {images}")})
    return blocks, outline


# ------------------------------------------------------------------- xlsx --


def column(n: int) -> str:
    """1 -> A, 27 -> AA."""
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def cell_text(value: Any) -> str:
    return "" if value is None else str(value).replace("\n", " ")


def xlsx_blocks(path: Path) -> tuple[list[Block], list[dict[str, Any]]]:
    """(blocks for search, sheets with their sizes). Reads by sheet and range go
    to the workbook itself (reading.py): exact cells, formulas on request."""
    import openpyxl

    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    blocks: list[Block] = []
    sheets = []
    try:
        for ws in book.worksheets:
            rows = [[cell_text(v) for v in r] for r in ws.iter_rows(values_only=True)]
            while rows and not any(rows[-1]):
                rows.pop()
            width = max((len(r) for r in rows), default=0)
            sheets.append({"name": ws.title, "rows": len(rows), "cols": width})
            if not rows:
                continue
            header = rows[0]
            for start in range(1, len(rows), XLSX_ROWS):
                chunk = rows[start:start + XLSX_ROWS]
                first, last = start + 1, start + len(chunk)
                lines = [" | ".join(header)] + [f"{first + i}: " + " | ".join(r) for i, r in enumerate(chunk)]
                blocks.append({"id": f"{ws.title}!A{first}:{column(width)}{last}", "kind": "rows",
                               "section": ws.title, "text": "\n".join(lines)})
            if len(rows) == 1:
                blocks.append({"id": f"{ws.title}!A1:{column(width)}1", "kind": "rows",
                               "section": ws.title, "text": " | ".join(header)})
    finally:
        book.close()
    return blocks, sheets
