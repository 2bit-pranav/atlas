"""Read a PDF's text layer.

Uses pypdfium2, which is the only PDF text library installed -- there is no
pypdf, pdfminer or pymupdf here. It is fast and it does not pull in a document
model, which is the point.

**A PDF with no text layer returns an error, not an empty answer.** That is the
single most important behaviour in this script. A scanned PDF, or an image-only
export, has nothing to extract; returning "" would let the model report "the
document contains no information" when the truth is "I cannot read this kind of
document". Those are very different statements and the user can only tell them
apart if the tool says so.
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
    header,
    image_line,
    images_dir,
    limit_for,
    main_wrapper,
    require,
    resolve,
    truncate,
)

pdfium, = require("pypdfium2")


def parse_pages(spec: str, total: int) -> list[int]:
    """`1-3,7` -> [0, 1, 2, 6] (1-based in, 0-based out).

    `all` is accepted because the SKILL.md documents it. It was not, and the
    failure mode was an error message about "no pages in --pages 'all'" -- a
    correct message about an input the docs told the model to send.
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


def page_images(doc, index: int, source: Path, budget: list[int]) -> list[str]:
    """Save the images on one page and return their Markdown lines.

    Rendered with their masks applied (`render=True`), so a transparent PNG or
    an image drawn through a soft mask looks the way it does on the page.
    """
    import pypdfium2.raw as raw

    lines = []
    for n, obj in enumerate(doc[index].get_objects(filter=(raw.FPDF_PAGEOBJ_IMAGE,)), start=1):
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
    parser.add_argument("--pages", default="1-2",
                        help="page range, 1-based, e.g. 1-3 or 1,4,7")
    # nargs="*" for the same reason query_xlsx's SQL takes it: `cmd.exe` splits a
    # quoted value on its spaces before argparse sees it, so a two-word search
    # term arrives as three arguments and the extras are rejected.
    parser.add_argument("--search", nargs="*", default=[],
                        help="print only pages containing this text")
    parser.add_argument("--no-images", action="store_true",
                        help="do not save the pages' images")
    add_common_arguments(parser)
    args = parser.parse_args()

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
        for i in range(total):
            text = doc[i].get_textpage().get_text_range()
            if needle in text.lower():
                hits.append((i, text))
        print(header(file=path.name, pages=total, search=" ".join(args.search),
                     pages_with_match=len(hits)))
        print()
        if not hits:
            print(f"(no page contains {needle!r})")
            return 0
        limit, hint = limit_for(args)
        per_page = max(200, limit // max(1, len(hits)))
        body = []
        for i, text in hits:
            # Show the match in context, not just the whole page. A search hit
            # buried in 3000 characters is a search hit the model has to
            # re-find.
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

    pages = parse_pages(args.pages, total)
    if not pages:
        return fail(f"no pages in --pages {args.pages!r} (document has {total})")

    limit, hint = limit_for(args)
    chunks = []
    empty_pages = []
    images = 0
    budget = [MAX_IMAGES]
    for i in pages:
        text = doc[i].get_textpage().get_text_range()
        found = [] if args.no_images else page_images(doc, i, path, budget)
        images += len(found)
        if not text.strip() and not found:
            empty_pages.append(i + 1)
        # Images go after the page's text: their place in the page is not
        # recoverable from the text layer, and "after" keeps them on the page.
        chunks.append("\n".join([f"--- page {i + 1} of {total} ---", text.strip(), *found]).strip())

    body = "\n\n".join(chunks)

    if empty_pages and len(empty_pages) == len(pages):
        return fail(
            f"pages {empty_pages} have no text layer -- this looks like a "
            "scanned or image-only PDF",
            hint="image-only PDFs cannot be read by any tool here; say so "
                 "plainly rather than guessing at the contents",
        )

    limit, hint = limit_for(args)
    text, cut = truncate(body, limit, more_hint=f"--pages <range> {hint}")
    print(header(file=path.name, pages=total, read=", ".join(
        str(i + 1) for i in pages), truncated=cut or "no",
               empty_pages=empty_pages or "none", images=images))
    if images:
        print("images: saved; keep a ![...](...) line in create_document's Markdown to keep that image")
    print()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))