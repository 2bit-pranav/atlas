"""Split a PDF into several PDFs.

    python split_pdf.py report.pdf                 # one file per page
    python split_pdf.py report.pdf 1-3 4-10 11-    # one file per range

Files are named after the source and the pages: `report_p1-3.pdf`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import created, fail, main_wrapper, output_path, page_list, require, resolve  # noqa: E402

pdfium, = require("pypdfium2")

#: One file per page stops here, so a 500-page book does not become 500 files.
MAX_FILES = 100


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("ranges", nargs="*", help="page ranges, one output file each (default: every page)")
    parser.add_argument("--out-dir", default=".", help="folder for the parts (default: the workspace)")
    args = parser.parse_args()

    path = resolve(args.file)
    if not path.is_file():
        return fail(f"no such file: {path}")
    src = pdfium.PdfDocument(str(path))
    total = len(src)
    ranges = args.ranges or [str(n) for n in range(1, total + 1)]
    if len(ranges) > MAX_FILES:
        return fail(f"{total} pages would make {len(ranges)} files", hint="give page ranges instead, e.g. 1-50 51-")
    folder = output_path(args.out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for spec in ranges:
        try:
            pages = page_list(spec, total)
        except ValueError as exc:
            return fail(str(exc))
        part = pdfium.PdfDocument.new()
        part.import_pages(src, pages=pages)
        out = folder / f"{path.stem}_p{spec.replace(',', '_').rstrip('-') + ('-' + str(total) if spec.endswith('-') else '')}.pdf"
        part.save(str(out))
        names.append(f"{out.name} ({len(pages)} page{'s' * (len(pages) != 1)})")
    print(created(", ".join(names), files=len(names)))
    return 0


if __name__ == "__main__":
    sys.exit(main_wrapper(main))
