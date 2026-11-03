"""The ingest store (agent/ingest/) and the document read tools (agent/tools/doc_reading.py)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent.ingest.store import Store
from agent.tools.doc_reading import doc_read_tools, parse_pages
from agent.tools.documents.create import create
from agent.tools.reading import MAX_CHARS


def _pdf(path: Path, pages: list[str], image: bool = False) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate

    s = getSampleStyleSheet()
    story: list = []
    for text in pages:
        story += [Paragraph(text, s["BodyText"]), PageBreak()]
    if image:
        from PIL import Image as PILImage

        png = path.with_suffix(".png")
        PILImage.new("RGB", (300, 200), "navy").save(png)
        story.insert(1, Image(str(png), width=150, height=100))
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path


def _scan(path: Path, text: str) -> Path:
    """One image-only page holding `text`."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(img).text((100, 200), text, fill="black", font=ImageFont.truetype("arial.ttf", 40))
    img.save(path, resolution=150)
    return path


def _docx(path: Path) -> Path:
    from docx import Document

    d = Document()
    d.add_heading("Report", 0)
    d.add_heading("Background", 1)
    d.add_paragraph("We reviewed three suppliers.")
    d.add_heading("Findings", 1)
    d.add_heading("Prices", 2)
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Supplier", "Lead time"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Brightline", "23 days"
    d.save(str(path))
    return path


def _xlsx(path: Path) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Mar"
    ws.append(["region", "revenue"])
    for row in (["North", 4100.5], ["South", 2950.25], *([["East", 100]] * 9), ["West", "n/a"]):
        ws.append(row)
    wb.save(str(path))
    return path


def _ready(store: Store, sha: str | None) -> dict:
    assert sha
    e = store.wait(sha, lambda e: e["status"] == "ready", 60)
    assert e and e["status"] == "ready", e
    return e


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "ws").mkdir()
    return tmp_path / "ws"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "parsed")


def _tools(store: Store, ws: Path, chat: str = "c1", tainted: list | None = None):
    pdf, docx, xlsx = doc_read_tools(store, chat, lambda p: ws / p, ws,
                                     (lambda: tainted.append(1)) if tainted is not None else None)
    return pdf, docx, xlsx


def _text(result) -> str:
    return result if isinstance(result, str) else result["content"][0]["text"]


# ----------------------------------------------------------------- store --


def test_ingest_is_idempotent_and_keyed_by_content(store, ws) -> None:
    a = _pdf(ws / "a.pdf", ["Alpha page one.", "Alpha page two."])
    sha = store.submit(a, "c1")
    e = _ready(store, sha)
    assert e["pages"] == 2 and [b["id"] for b in store.blocks(sha)] == ["p1.1", "p2.1"]
    stamp = e["updated"]
    assert store.submit(a, "c1") == sha and store.entry(sha)["updated"] == stamp   # a cache hit
    copy = ws / "copy.pdf"
    copy.write_bytes(a.read_bytes())
    assert store.submit(copy, "c2") == sha                                         # same content, one entry


def test_a_scanned_page_is_read_by_ocr_and_a_text_page_is_not(store, ws) -> None:
    text = _pdf(ws / "t.pdf", ["A page with a text layer."])
    scan = _scan(ws / "s.pdf", "Invoice number INV-58213")
    t, s = store.submit(text, "c1"), store.submit(scan, "c1")
    assert _ready(store, t)["page_status"] == ["text"]
    e = _ready(store, s)
    assert e["page_status"] == ["ocr"]
    assert "INV-58213" in " ".join(b["text"] for b in store.blocks(s))


def test_search_finds_words_not_the_phrase(store, ws) -> None:
    pages = [f"Filler about module {i}." for i in range(30)]
    pages[26] = "The calibration constant for sensor K7 is 4.183 volts per unit."
    sha = store.submit(_pdf(ws / "m.pdf", pages), "c1")
    _ready(store, sha)
    hits = store.search(sha, "sensor K7 calibration constant")
    assert hits and hits[0]["page"] == 27


def test_docx_blocks_carry_edit_addresses_and_sections(store, ws) -> None:
    sha = store.submit(_docx(ws / "r.docx"), "c1")
    e = _ready(store, sha)
    blocks = store.blocks(sha)
    assert [o["section"] for o in e["outline"]] == ["1", "2", "2.1"]       # the Title is not a section
    table = next(b for b in blocks if b["kind"] == "table")
    assert table["id"] == "t1" and table["section"] == "2.1" and "Brightline | 23 days" in table["text"]
    para = next(b for b in blocks if b["text"] == "We reviewed three suppliers.")
    assert para["id"] == "b3" and para["section"] == "1"


def test_nothing_is_written_beside_the_source(store, ws) -> None:
    pdf = _pdf(ws / "img.pdf", ["Text with a figure."], image=True)
    (ws / "img.png").unlink()
    before = sorted(p.name for p in ws.rglob("*"))
    _ready(store, store.submit(pdf, "c1"))
    _ready(store, store.submit(_docx(ws / "r.docx"), "c1"))
    assert sorted(p.name for p in ws.rglob("*")) == sorted([*before, "r.docx"])


def test_images_resolve_only_for_a_chat_that_owns_the_document(store, ws, tmp_path) -> None:
    sha = store.submit(_pdf(ws / "img.pdf", ["Text with a figure."], image=True), "c1")
    _ready(store, sha)
    line = next(b["text"] for b in store.blocks(sha) if b["kind"] == "image")
    ref = line.split("(", 1)[1].rstrip(")")
    assert ref.startswith("asset:") and store.asset("c1", ref) is not None
    assert store.asset("c2", ref) is None                                   # another chat
    assert store.asset("c1", ref.replace(".png", "/../../index.db")) is None
    out = tmp_path / "out.docx"
    info = create(out, f"# Copy\n\n{line}\n", base=ws, asset=lambda r: store.asset("c2", r))
    assert info["missing_images"]                                           # c2 cannot embed it
    info = create(out, f"# Copy\n\n{line}\n", base=ws, asset=lambda r: store.asset("c1", r))
    assert not info["missing_images"]


def test_deleting_the_last_owner_removes_the_entry(store, ws) -> None:
    sha = store.submit(_pdf(ws / "img.pdf", ["Figure."], image=True), "c1")
    _ready(store, sha)
    store.own("c2", sha)
    store.forget_chat("c1")
    assert store.entry(sha) is not None                                     # c2 still has it
    store.forget_chat("c2")
    assert store.entry(sha) is None and store.blocks(sha) == [] and not (store.root / sha).exists()


def test_parse_pages() -> None:
    assert parse_pages("1-3,7", 10) == [1, 2, 3, 7]
    assert parse_pages("9-20", 10) == [9, 10]
    assert parse_pages("x", 10) == []


# ----------------------------------------------------------------- tools --


def test_read_pdf_long_document_shows_page_one_and_says_what_is_left(store, ws) -> None:
    pages = [f"Section {i}: " + "words " * 200 for i in range(1, 41)]
    pages[26] = "The calibration constant for sensor K7 is 4.183."
    _pdf(ws / "manual.pdf", pages)
    read_pdf, _, _ = _tools(store, ws)
    out = read_pdf(path="manual.pdf")
    assert out.startswith("manual.pdf: page 1 of 40") and "NOT shown" in out and len(out) < MAX_CHARS + 800
    assert out.index('search=') < out.index('To read on')                 # search is offered first
    hit = read_pdf(path="manual.pdf", search="sensor K7 calibration")
    assert "page 27" in hit and "4.183" in hit
    assert "--- page 27 of 40 ---" in read_pdf(path="manual.pdf", pages="27")


def test_read_tools_name_the_right_tool_for_the_wrong_type(store, ws) -> None:
    _docx(ws / "r.docx")
    read_pdf, read_docx, read_xlsx = _tools(store, ws)
    assert 'read_docx(path="r.docx")' in _text(read_pdf(path="r.docx"))
    assert "Files in your workspace: r.docx" in _text(read_docx(path="gone.docx"))
    assert "not a link" in _text(read_pdf(path="file:///C:/Windows/x.pdf"))   # would bypass the access check


def test_read_docx_sections_and_ids(store, ws) -> None:
    _docx(ws / "r.docx")
    _, read_docx, _ = _tools(store, ws)
    whole = read_docx(path="r.docx")
    assert "[t1: table, 2 rows x 2 cols; a cell is t1.rROW.cCOL]" in whole
    assert "## 2.1 Prices" in whole
    part = read_docx(path="r.docx", section="2")
    assert "Prices" in part and "We reviewed" not in part
    assert "Sections: 1, 2, 2.1" in _text(read_docx(path="r.docx", section="9"))


def test_read_xlsx_grid_and_sql(store, ws) -> None:
    _xlsx(ws / "sales.xlsx")
    _, _, read_xlsx = _tools(store, ws)
    out = read_xlsx(path="sales.xlsx")
    assert "Mar (13 rows x 2 cols)" in out and "2 | North | 4100.5" in out
    assert "3 | South | 2950.25" in read_xlsx(path="sales.xlsx", range="Mar!A3:B3")
    total = read_xlsx(path="sales.xlsx", sql='SELECT SUM("revenue") FROM "Mar"')
    assert "7950.75" in total and "1 cell in number columns held text" in total   # "n/a" is NULL, and said
    bad = _text(read_xlsx(path="sales.xlsx", sql='SELECT * FROM "Mar" WHERE "region" = "North"'))
    assert "single quotes" in bad
    assert "only one SELECT" in _text(read_xlsx(path="sales.xlsx", sql='DROP TABLE "Mar"'))


def test_a_scan_read_waits_for_the_page_it_asks_for(store, ws) -> None:
    _scan(ws / "s.pdf", "Delivery note DN-4471")
    read_pdf, _, _ = _tools(store, ws)
    start = time.monotonic()
    out = read_pdf(path="s.pdf", pages="1")
    assert "DN-4471" in out and "(scanned, read by OCR)" in out
    assert time.monotonic() - start < 30


def test_a_file_that_cannot_be_parsed_reads_as_failed(store, ws) -> None:
    """Not 'still being read' forever: the first failure of a new file has no row to update."""
    bad = ws / "broken.docx"
    bad.write_text("| Brightline | 9.85 | 18 days |\n")      # what `sed -i` left of a .docx
    _, read_docx, _ = _tools(store, ws)
    out = _text(read_docx(path="broken.docx"))
    assert "could not be read" in out
