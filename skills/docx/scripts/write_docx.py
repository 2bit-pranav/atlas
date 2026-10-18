"""Create or overwrite a .docx.

Needed because "write me a summary of this" otherwise ends with the model
pasting prose into the chat and the user saving it by hand. Letting the agent
drop a real file in the chat directory is the obvious win.

Deliberately minimal: headings, paragraphs, bullets, and tables. A rich
document model is out of scope and adding one feature at a time
is how a writer script becomes a project.

Reads a tiny JSON description from stdin so the model never has to compose
python-docx code:

    {"blocks": [
        {"type": "heading", "text": "Findings"},
        {"type": "para", "text": "The total was 425184.67."},
        {"type": "bullet", "text": "March"},
        {"type": "table", "header": ["sheet", "total"],
         "rows": [["Jan", "489337.15"]]}
    ]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import fail, header, main_wrapper, resolve  # noqa: E402

import docx  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a .docx from JSON on stdin")
    parser.add_argument("path", help="output path (relative names go to the chat dir)")
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    raw = sys.stdin.read().strip()
    if not raw:
        return fail("expected a JSON document on stdin",
                    hint='see the SKILL.md for the shape')
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        return fail(f"stdin is not valid JSON: {exc}")

    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return fail('the JSON needs a "blocks" list with at least one entry')

    out = resolve(args.path)
    out.parent.mkdir(parents=True, exist_ok=True)

    document = docx.Document()
    if args.title or spec.get("title"):
        document.add_heading(args.title or spec["title"], level=0)

    written = {"heading": 0, "para": 0, "bullet": 0, "table": 0, "skipped": 0}
    for block in blocks:
        if not isinstance(block, dict):
            written["skipped"] += 1
            continue
        kind = block.get("type", "para")
        if kind == "heading":
            level = int(block.get("level", 1))
            document.add_heading(str(block.get("text", "")), level=level)
            written["heading"] += 1
        elif kind == "bullet":
            document.add_paragraph(str(block.get("text", "")), style="List Bullet")
            written["bullet"] += 1
        elif kind == "table":
            rows = block.get("rows") or []
            head = block.get("header")
            if not rows and not head:
                written["skipped"] += 1
                continue
            table = document.add_table(rows=0, cols=len(head) if head else
                                      max(len(r) for r in rows))
            table.style = "Table Grid"
            if head:
                # add_table(rows=0) creates NO rows, so rows[0] is an
                # IndexError. The header row has to be added like any other.
                cells = table.add_row().cells
                for cell, value in zip(cells, head):
                    cell.text = str(value)
            for row in rows:
                cells = table.add_row().cells
                for cell, value in zip(cells, row):
                    cell.text = str(value)
            written["table"] += 1
        else:
            document.add_paragraph(str(block.get("text", "")))
            written["para"] += 1

    document.save(str(out))
    print(header(written=str(out), bytes=out.stat().st_size, **written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))