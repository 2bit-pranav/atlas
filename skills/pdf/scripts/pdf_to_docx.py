"""Convert a PDF into an editable Word document.

    python pdf_to_docx.py report.pdf                 # writes report.docx
    python pdf_to_docx.py report.pdf out.docx --pages 2-5

Uses pdf2docx, which rebuilds paragraphs, tables and images from the layout.
A scanned PDF has no text to rebuild: the result would be pictures of pages.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import created, fail, main_wrapper, output_path, page_list, require, resolve  # noqa: E402

warnings.filterwarnings("ignore")      # PyMuPDF's deprecation notice for `fitz`
pdf2docx, = require("pdf2docx")
logging.disable(logging.INFO)          # pdf2docx logs every page; the model needs the result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("output", nargs="?", help="the .docx to write (default: same name)")
    parser.add_argument("--pages", default="all", help="e.g. 1-3,7 (default: all)")
    args = parser.parse_args()

    path = resolve(args.file)
    if not path.is_file():
        return fail(f"no such file: {path}")
    out = output_path(args.output or path.with_suffix(".docx").name)
    if out.suffix.lower() != ".docx":
        return fail(f"the output must be a .docx, not {out.name}")

    converter = pdf2docx.Converter(str(path))
    try:
        pages = page_list(args.pages, len(converter.fitz_doc))
    except ValueError as exc:
        converter.close()
        return fail(str(exc))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        converter.convert(str(out), pages=pages)
    converter.close()
    print(created(out, pages=len(pages), note="layout is rebuilt, so check complex pages"))
    return 0


if __name__ == "__main__":
    sys.exit(main_wrapper(main))
