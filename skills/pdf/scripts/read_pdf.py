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
    add_common_arguments,
    fail,
    header,
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
    for i in pages:
        text = doc[i].get_textpage().get_text_range()
        if not text.strip():
            empty_pages.append(i + 1)
        chunks.append(f"--- page {i + 1} of {total} ---\n{text.strip()}")

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
               empty_pages=empty_pages or "none"))
    print()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))