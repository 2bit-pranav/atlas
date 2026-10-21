"""OCR for the parts of a PDF that have no text layer.

Used by `read_pdf.py`, which decides per page:

* a page with a text layer gives its text;
* a page with (almost) no text layer -- a scan, a photo of a page -- is
  rendered and read with OCR;
* a text page that also carries a large picture (a scanned table pasted into
  a report) gets that picture read too, kept only when it holds real text.

RapidOCR runs PaddleOCR's models on onnxruntime on the CPU, with no system
install (no Tesseract); about 1.5-2 s per page. Results are cached beside the
document's extracted images, so re-reading the same pages is instant.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

#: A page is scanned when its text layer has fewer characters than this and
#: one image covers most of it. A short caption above a diagram is not a scan.
SCANNED_BELOW_CHARS = 40
SCAN_MIN_AREA = 0.5
#: A picture on a text page is read when it covers at least this share of the page.
PICTURE_MIN_AREA = 0.12
#: OCR text from a picture is kept only when it looks like text, not a diagram.
PICTURE_MIN_CHARS = 20
PICTURE_MIN_SCORE = 0.75
#: Rendered page width in pixels: enough for 9-10 pt text.
RENDER_WIDTH_PX = 1800

_engine: Any = None


def engine() -> Any:
    """The OCR engine, built once. Quiet: its INFO logging would reach the model."""
    global _engine
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
    """Group detected boxes into lines, top to bottom, left to right.

    Boxes on one visual line (centres within half a line height) are joined
    with spaces, so a table row stays one row instead of one cell per line.
    """
    items = []
    for box, text in zip(boxes, texts):
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


# ------------------------------------------------------------------ cache --


class Cache:
    """OCR results for one PDF, kept beside its extracted images.

    Keyed by the file's size and modification time, so an edited file is read
    again rather than answered from a stale cache.
    """

    def __init__(self, folder: Path, source: Path) -> None:
        self.path = folder / "ocr.json"
        stat = source.stat()
        self.sig = f"{stat.st_size}-{int(stat.st_mtime)}"
        self.data: dict[str, Any] = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("sig") == self.sig:
                self.data = loaded.get("entries", {})
        except (OSError, json.JSONDecodeError):
            pass
        self.dirty = False

    def get(self, key: str) -> tuple[str, float] | None:
        hit = self.data.get(key)
        return (hit[0], hit[1]) if hit else None

    def put(self, key: str, value: tuple[str, float]) -> None:
        self.data[key] = list(value)
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"sig": self.sig, "entries": self.data}), encoding="utf-8")


def _pictures(page: Any) -> list[tuple[int, Any, float]]:
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


#: An image covering this much of a page is the page itself: a scan.
PAGE_SIZED = 0.85


def page_sized(page: Any) -> set[int]:
    """Numbers of the images that fill the page (the scan of a scanned page)."""
    return {n for n, _, share in _pictures(page) if share >= PAGE_SIZED}


def is_scanned(page: Any, text: str) -> bool:
    """Little or no text layer, and either nothing else or a page-sized image.

    A page with no text at all is always tried (its text may be drawn as
    shapes); one with a short caption is a scan only when an image covers
    most of it, so "Topology diagram:" above a drawing is left alone.
    """
    chars = len("".join(text.split()))
    if chars == 0:
        return True
    return chars < SCANNED_BELOW_CHARS and any(share >= SCAN_MIN_AREA for _, _, share in _pictures(page))


def read_scanned_page(page: Any, index: int, cache: Cache) -> tuple[str, float]:
    key = f"page{index + 1}"
    hit = cache.get(key)
    if hit is None:
        hit = read_image(render_page(page))
        cache.put(key, hit)
    return hit


def read_pictures(page: Any, index: int, cache: Cache) -> list[str]:
    """Text found in a text page's large pictures, one entry per picture."""
    found = []
    for n, obj, share in _pictures(page):
        if share < PICTURE_MIN_AREA:
            continue
        try:
            key = f"page{index + 1}-image{n}"
            hit = cache.get(key)
            if hit is None:
                try:
                    image = obj.get_bitmap(render=True).to_pil()
                except Exception:  # noqa: BLE001 - some filters only decode raw
                    image = obj.get_bitmap(render=False).to_pil()
                hit = read_image(image)
                cache.put(key, hit)
        except Exception:  # noqa: BLE001 - one odd picture must not lose the page
            continue
        text, score = hit
        if len("".join(text.split())) >= PICTURE_MIN_CHARS and score >= PICTURE_MIN_SCORE:
            found.append(f"[text in picture {n}, read by OCR]\n{text}")
    return found
