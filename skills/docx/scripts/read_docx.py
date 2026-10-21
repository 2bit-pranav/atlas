"""Read a Word document's text, headings and tables.

    python read_docx.py report.docx
    python read_docx.py report.docx --headings-only

python-docx only; no conversion or rendering. Pictures are saved beside the
document and printed as Markdown image lines.

Tables are kept, in document order, as pipe tables: a report's findings often
live in one, and text-only extraction would drop the numbers. The header
counts them, so a truncated read still says how many there are.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import (  # noqa: E402
    MAX_IMAGES,
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

docx, = require("docx")


def iter_blocks(document) -> list[tuple[str, object]]:
    """Paragraphs and tables in document order.

    python-docx lists them separately; reading them that way would put a table
    before the sentence that introduces it.
    """
    body = document.element.body
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield "p", Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield "t", Table(child, document)


BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def paragraph_images(paragraph, document, source: Path, budget: list[int]) -> list[str]:
    """Save the pictures inside one paragraph; return their Markdown lines."""
    lines = []
    for blip in paragraph._p.iter(BLIP):
        if budget[0] <= 0:
            break
        rid = blip.get(EMBED)
        part = document.part.related_parts.get(rid) if rid else None
        if part is None or not getattr(part, "blob", None):
            continue
        ext = Path(getattr(part, "partname", "image.png")).suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
            continue  # EMF/WMF etc.: a rewritten PDF or Word file may not draw them
        budget[0] -= 1
        target = images_dir(source) / f"image{MAX_IMAGES - budget[0]}{ext}"
        target.write_bytes(part.blob)
        lines.append(image_line(target, f"image {MAX_IMAGES - budget[0]}"))
    return lines


def render_table(table, max_rows: int) -> tuple[str, bool]:
    rows = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        rows.append(cells)
    if not rows:
        return "", False
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    cut = len(rows) > max_rows
    rows = rows[:max_rows]
    head, *rest = rows
    lines = ["| " + " | ".join(head) + " |",
             "|" + "|".join(["---"] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rest]
    if cut:
        lines.append(f"[table truncated: {len(table.rows)} rows total]")
    return "\n".join(lines), cut


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a .docx")
    parser.add_argument("path")
    parser.add_argument("--headings-only", action="store_true",
                        help="print just the outline")
    parser.add_argument("--max-table-rows", type=int, default=20)
    parser.add_argument("--no-images", action="store_true", help="do not save the images")
    add_common_arguments(parser)
    args = parser.parse_args()

    path = resolve(args.path)
    if not path.is_file():
        return fail(f"no such file: {path}")
    if path.suffix.lower() != ".docx":
        return fail(f"{path.name} is not a .docx",
                    hint="legacy .doc files are not supported; ask the user to "
                         "save as .docx")

    document = docx.Document(str(path))
    blocks = list(iter_blocks(document))
    tables = [b for kind, b in blocks if kind == "t"]
    headings = [
        b.text.strip() for kind, b in blocks
        if kind == "p" and b.style.name.startswith("Heading") and b.text.strip()
    ]

    if args.headings_only:
        limit, hint = limit_for(args)
        body, cut = truncate("\n".join(headings) or "(no headings)",
                             limit, more_hint=hint)
        print(header(file=path.name, headings=len(headings), tables=len(tables)))
        print()
        print(body)
        return 0

    limit, hint = limit_for(args)
    parts = []
    dropped_tables = 0
    images = 0
    budget = [MAX_IMAGES]
    for kind, block in blocks:
        if kind == "p":
            text = block.text.strip()
            if text:
                marker = "#" if block.style.name.startswith("Heading") else ""
                parts.append(f"{marker} {text}")
            if not args.no_images:
                found = paragraph_images(block, document, path, budget)
                images += len(found)
                parts.extend(found)
        else:
            rendered, was_cut = render_table(block, args.max_table_rows)
            if rendered:
                parts.append("[table]\n" + rendered)
            else:
                dropped_tables += 1

    body, cut = truncate("\n\n".join(parts), limit, more_hint=hint)
    print(header(file=path.name, headings=len(headings), tables=len(tables),
                 empty_tables=dropped_tables, truncated=cut or "no", images=images))
    print()
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))