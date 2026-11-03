"""OCR for the parts of a PDF that have no text layer (from skills/pdf/scripts/_ocr.py).

Decided per page: a page with a text layer gives its text; a page with
(almost) none -- a scan, a photo of a page -- is rendered and read with OCR; a
text page carrying a large picture (a scanned table pasted into a report) gets
that picture read too, kept only when it holds real text.

RapidOCR runs PaddleOCR's models on onnxruntime on the CPU, no system install;
about 2 s per page. Results are stored by the ingest store, not here.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

#: A page is scanned when its text layer has fewer characters than this and one
#: image covers most of it. A short caption above a diagram is not a scan.
SCANNED_BELOW_CHARS = 40
SCAN_MIN_AREA = 0.5
#: A picture on a text page is read when it covers at least this share of the page.
PICTURE_MIN_AREA = 0.12
#: OCR text from a picture is kept only when it looks like text, not a diagram.
PICTURE_MIN_CHARS = 20
PICTURE_MIN_SCORE = 0.75
#: Rendered page width in pixels: enough for 9-10 pt text.
RENDER_WIDTH_PX = 1800
#: An image covering this much of a page is the page itself: a scan.
PAGE_SIZED = 0.85

_engine: Any = None
_lock = threading.Lock()


def engine() -> Any:
    """The OCR engine, built once. Quiet: its INFO logging would reach the logs as noise."""
    global _engine
    with _lock:
        if _engine is None:
            logging.getLogger("RapidOCR").setLevel(logging.ERROR)
            from rapidocr import RapidOCR

            _engine = RapidOCR(params={"Global.log_level": "error"})
    return _engine


def read_image(image: Any) -> tuple[str, float]:
    """OCR one PIL image: (text in reading order, mean confidence)."""
    result = engine()(image)
    boxes, texts, scores = result.boxes, result.txts, result.scores
    if boxes is None or not texts:
        return "", 0.0
    return _lines(list(boxes), list(texts)), float(sum(scores) / len(scores))


def _lines(boxes: list[Any], texts: list[str]) -> str:
    """Boxes on one visual line (centres within half a line height) joined with
    spaces, top to bottom, so a table row stays one row."""
    items = []
    for box, text in zip(boxes, texts, strict=False):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), text))
    items.sort(key=lambda i: (i[0], i[2]))
    lines: list[list[tuple[float, float, float, str]]] = []
    for item in items:
        if lines and abs(item[0] - lines[-1][0][0]) <= max(item[1], lines[-1][0][1]) / 2:
            lines[-1].append(item)
        else:
            lines.append([item])
    return "\n".join("  ".join(t for *_, t in sorted(line, key=lambda i: i[2])) for line in lines)


def render_page(page: Any) -> Any:
    width, _ = page.get_size()
    scale = max(1.0, min(4.0, RENDER_WIDTH_PX / max(1.0, width)))
    return page.render(scale=scale).to_pil()


def pictures(page: Any) -> list[tuple[int, Any, float]]:
    """(number, image object, share of the page it covers) for each image."""
    import pypdfium2.raw as raw

    width, height = page.get_size()
    area = max(1.0, width * height)
    out = []
    for n, obj in enumerate(page.get_objects(filter=(raw.FPDF_PAGEOBJ_IMAGE,)), start=1):
        try:
            left, bottom, right, top = obj.get_bounds()
        except Exception:  # noqa: BLE001
            continue
        out.append((n, obj, min(1.0, abs(right - left) * abs(top - bottom) / area)))
    return out


def is_scanned(page: Any, text: str) -> bool:
    """No text at all, or a short caption with a page-sized image."""
    chars = len("".join(text.split()))
    if chars == 0:
        return True
    return chars < SCANNED_BELOW_CHARS and any(share >= SCAN_MIN_AREA for _, _, share in pictures(page))


def bitmap(obj: Any) -> Any:
    try:
        return obj.get_bitmap(render=True).to_pil()
    except Exception:  # noqa: BLE001 - some filters only decode raw
        return obj.get_bitmap(render=False).to_pil()


def picture_text(page: Any) -> list[str]:
    """Text found in a text page's large pictures, one entry per picture."""
    found = []
    for n, obj, share in pictures(page):
        if share < PICTURE_MIN_AREA:
            continue
        try:
            text, score = read_image(bitmap(obj))
        except Exception:  # noqa: BLE001 - one odd picture must not lose the page
            continue
        if len("".join(text.split())) >= PICTURE_MIN_CHARS and score >= PICTURE_MIN_SCORE:
            found.append(f"[text in picture {n}, read by OCR]\n{text}")
    return found
