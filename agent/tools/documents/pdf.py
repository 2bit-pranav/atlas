"""PDF: writing a document from blocks with reportlab, and checking it."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.tools.documents.base import DocumentError
from agent.tools.documents.images import _image_size
from agent.tools.documents.markdown import Block, Run, plain

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
    from reportlab.platypus import (
        HRFlowable,
        ListFlowable,
        ListItem,
        Paragraph,
        Preformatted,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

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


__all__ = []
