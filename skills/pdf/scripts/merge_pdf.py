"""Combine PDFs, or chosen pages of them, into one PDF.

    python merge_pdf.py out.pdf a.pdf b.pdf:2-5 c.pdf:1,3,7-

Each input is a file, optionally followed by `:pages`. Pages are 1-based,
kept in the order written (`3,1-2` puts page 3 first), `5-` runs to the end,
and no `:pages` means all of them. The same file may appear more than once.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import created, fail, main_wrapper, output_path, page_list, require, resolve, unquote  # noqa: E402

pdfium, = require("pypdfium2")

#: `file.pdf:1-3,7` -- the suffix only counts when it looks like pages, so a
#: drive letter (`C:/x.pdf`) is never mistaken for one.
_SPEC = re.compile(r"^(?P<file>.+?):(?P<pages>(?:all|[\d,\s-]+))$", re.I)


def split_spec(arg: str) -> tuple[Path, str]:
    arg = unquote(arg)
    m = _SPEC.match(arg)
    return (resolve(m["file"]), m["pages"]) if m else (resolve(arg), "all")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="the PDF to write, e.g. combined.pdf")
    parser.add_argument("inputs", nargs="+", help="file.pdf or file.pdf:pages")
    args = parser.parse_args()

    out = output_path(args.output)
    if out.suffix.lower() != ".pdf":
        return fail(f"the output must be a .pdf, not {out.name}")
    merged = pdfium.PdfDocument.new()
    used = []
    for arg in args.inputs:
        path, spec = split_spec(arg)
        if not path.is_file():
            return fail(f"no such file: {path}", hint="the first argument is the output; inputs come after it")
        src = pdfium.PdfDocument(str(path))
        try:
            pages = page_list(spec, len(src))
        except ValueError as exc:
            return fail(f"{path.name}: {exc}")
        merged.import_pages(src, pages=pages)
        used.append(f"{path.name} ({'all' if spec == 'all' else spec}: {len(pages)} page{'s' * (len(pages) != 1)})")
    if out.exists() and any(split_spec(a)[0].resolve() == out.resolve() for a in args.inputs):
        return fail("the output would overwrite one of the inputs; give it a new name")
    merged.save(str(out))
    total = len(pdfium.PdfDocument(str(out)))
    print(created(out, pages=total, sources="; ".join(used)))
    return 0


if __name__ == "__main__":
    sys.exit(main_wrapper(main))
