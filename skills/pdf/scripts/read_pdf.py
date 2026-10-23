"""Read a PDF: its text layer, and OCR wherever there is none.

    python read_pdf.py report.pdf --pages 1-3
    python read_pdf.py report.pdf --search net revenue

One command for every PDF, decided per page (`_ocr.py`): text pages give their
text layer (pypdfium2); scanned pages are read with OCR; large pictures on text
pages are read too when they hold text. Scanned pages are marked in the output.
There is deliberately no separate "scanned" reader: given two, the model takes
the first it sees.

**Nothing readable is an error, not an empty answer**, so the model cannot
report "the document contains no information".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import (  # noqa: E402
    MAX_IMAGES,
    MIN_IMAGE_PX,
    add_common_arguments,
    fail,
    fetch,
    header,
    image_line,
    images_dir,
    is_link,
    limit_for,
    main_wrapper,
    require,
    resolve,
    truncate,
)

pdfium, = require("pypdfium2")
import _ocr  # noqa: E402 - beside this script


#: A document this short is read whole when no --pages is given.
SHORT_DOC = 5
#: The most pages one call reads.
MAX_PAGES = 15


def parse_pages(spec: str, total: int) -> list[int]:
    """`1-3,7` -> [0, 1, 2, 6] (1-based in, 0-based out), sorted and deduplicated.

    `all` / `*` mean every page (SKILL.md documents `all`). Unparseable parts and
    pages out of range are dropped; the caller fails if nothing is left.
    """
    if (spec or "").strip().lower() in ("all", "*"):
        return list(range(total))
    out: list[int] = []
    for part in (spec or "1").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            out.extend(range(start - 1, min(end, total)))
        else:
            try:
                out.append(int(part) - 1)
            except ValueError:
                continue
    return sorted({i for i in out if 0 <= i < total})


def page_images(doc, index: int, source: Path, budget: list[int], skip: set[int] = frozenset()) -> list[str]:
    """Save the images on one page and return their Markdown lines.

    Rendered with their masks applied (`render=True`), so a transparent PNG or
    an image drawn through a soft mask looks the way it does on the page.
    """
    import pypdfium2.raw as raw

    lines = []
    for n, obj in enumerate(doc[index].get_objects(filter=(raw.FPDF_PAGEOBJ_IMAGE,)), start=1):
        if n in skip:
            continue
        if budget[0] <= 0:
            break
        try:
            w, h = obj.get_px_size()
            if w < MIN_IMAGE_PX and h < MIN_IMAGE_PX:
                continue
            try:
                image = obj.get_bitmap(render=True).to_pil()
            except Exception:  # noqa: BLE001 - some filters only decode raw
                image = obj.get_bitmap(render=False).to_pil()
            target = images_dir(source) / f"page{index + 1}-{n}.png"
            image.save(target)
        except Exception:  # noqa: BLE001 - one odd image must not lose the text
            continue
        budget[0] -= 1
        lines.append(image_line(target, f"page {index + 1}, image {n}"))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Read text from a PDF")
    parser.add_argument("path", help="path to the PDF")
    parser.add_argument("--pages", default=None,
                        help="page range, 1-based, e.g. 1-3 or 1,4,7 (default: all of a short "
                             f"document, else 1-2; at most {MAX_PAGES} at once)")
    # nargs="*" and rejoined: `cmd.exe` can split a quoted multi-word term on
    # its spaces before argparse sees it (see _shared.join_sql).
    parser.add_argument("--search", nargs="*", default=[],
                        help="print only pages containing this text")
    parser.add_argument("--no-images", action="store_true",
                        help="do not save the pages' images")
    parser.add_argument("--no-ocr", action="store_true",
                        help="text layer only: skip OCR of scanned pages and pictures (faster)")
    add_common_arguments(parser)
    args = parser.parse_args()

    # A link (a PDF on the web, or file:///...) is fetched into the workspace first.
    source = ""
    if is_link(args.path):
        path, source = fetch(args.path, ".pdf", b"%PDF")
    else:
        path = resolve(args.path)
    if not path.is_file():
        return fail(f"no such PDF: {path}")

    doc = pdfium.PdfDocument(str(path))
    total = len(doc)
    if total == 0:
        return fail("the file has no pages")

    if args.search:
        needle = " ".join(args.search).lower()
        hits = []
        cache = _ocr.Cache(images_dir(path), path)
        ocr_pages: list[int] = []
        for i in range(total):
            # Scanned pages are searched through OCR too, so a search never
            # reports "no match" for text the reader would have found.
            text = page_text(doc, i, cache, ocr_pages, use_ocr=not args.no_ocr)
            if needle in text.lower():
                hits.append((i, text))
        cache.save()
        print(header(file=path.name, pages=total, search=" ".join(args.search),
                     pages_with_match=len(hits), ocr_pages=", ".join(map(str, ocr_pages)) or None))
        print()
        if not hits:
            print(f"(no page contains {needle!r})")
            return 0
        limit, hint = limit_for(args)
        per_page = max(200, limit // max(1, len(hits)))
        body = []
        for i, text in hits:
            # A snippet around the match, not the whole page, so the model does
            # not have to re-find it.
            low = text.lower()
            at = low.find(needle)
            start = max(0, at - 300)
            snippet = text[start:start + per_page]
            body.append(
                f"--- page {i + 1} ---\n{snippet}\n"
                f"[showing {len(snippet)} chars; full page: --pages {i + 1}]"
            )
        print("\n\n".join(body))
        return 0

    if args.pages is None:
        args.pages = "all" if total <= SHORT_DOC else "1-2"
    pages = parse_pages(args.pages, total)
    if not pages:
        return fail(f"no pages in --pages {args.pages!r} (document has {total})")
    if len(pages) > MAX_PAGES:
        # Every scanned page is read by OCR, seconds each: 67 pages took minutes
        # and printed far more than the output budget anyway.
        return fail(f"the document has {total} pages; read at most {MAX_PAGES} at once",
                    hint=f'find the pages that matter with --search "<word>", then read them, '
                         f"e.g. --pages 1-{MAX_PAGES}")

    cache = _ocr.Cache(images_dir(path), path)
    chunks = []
    empty_pages, ocr_pages, ocr_pictures = [], [], 0
    images = 0
    budget = [MAX_IMAGES]
    for i in pages:
        text = page_text(doc, i, cache, ocr_pages, use_ocr=not args.no_ocr)
        pictures = [] if args.no_ocr or (i + 1) in ocr_pages else _ocr.read_pictures(doc[i], i, cache)
        ocr_pictures += len(pictures)
        # On a scanned page the page-sized scan is not saved as an image: its
        # text is already above, and a rewrite would carry the page twice.
        skip = _ocr.page_sized(doc[i]) if (i + 1) in ocr_pages else set()
        found = [] if args.no_images else page_images(doc, i, path, budget, skip)
        images += len(found)
        if not text.strip() and not pictures and not found:
            empty_pages.append(i + 1)
        # Images follow the page's text: their position within it is unknown.
        title = f"--- page {i + 1} of {total}{' (scanned, read by OCR)' if (i + 1) in ocr_pages else ''} ---"
        chunks.append("\n".join([title, text.strip(), *pictures, *found]).strip())
    cache.save()

    body = "\n\n".join(chunks)

    if empty_pages and len(empty_pages) == len(pages):
        return fail(
            f"pages {empty_pages} have no text, even with OCR -- they are blank, "
            "or pictures without writing",
            hint="say so plainly rather than guessing at the contents",
        )

    limit, hint = limit_for(args)
    text, cut = truncate(body, limit, more_hint=f"--pages <range> {hint}")
    print(header(file=path.name, source=source or None, pages=total, read=", ".join(
        str(i + 1) for i in pages), truncated=cut or "no",
               empty_pages=empty_pages or "none", images=images,
               ocr_pages=", ".join(map(str, ocr_pages)) or None,
               ocr_pictures=ocr_pictures or None))
    if ocr_pages or ocr_pictures:
        print("ocr: text read from images can have recognition errors; quote numbers and names as printed")
    if images:
        print("images: saved; keep a ![...](...) line in create_document's Markdown to keep that image")
    print()
    print(text)
    return 0


def page_text(doc, index: int, cache, ocr_pages: list[int], *, use_ocr: bool) -> str:
    """The page's text layer, or its OCR text when it has (almost) none."""
    text = doc[index].get_textpage().get_text_range()
    if use_ocr and _ocr.is_scanned(doc[index], text):
        ocr_text, _score = _ocr.read_scanned_page(doc[index], index, cache)
        if ocr_text.strip():
            ocr_pages.append(index + 1)
            return ocr_text
    return text


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))