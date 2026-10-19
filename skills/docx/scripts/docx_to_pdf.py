"""Convert a Word document to PDF.

    python docx_to_pdf.py report.docx           # writes report.pdf
    python docx_to_pdf.py report.docx out.pdf

An exact conversion needs a program that lays out Word documents: Microsoft
Word (through docx2pdf) or LibreOffice. With neither installed the script says
so, and names the route that always works: read the document and create the
PDF from its Markdown, which keeps the text, tables and images but not the
exact layout.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import created, fail, main_wrapper, output_path, resolve  # noqa: E402

_SOFFICE = [r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]


def _word(src: Path, out: Path) -> str | None:
    """docx2pdf drives Word over COM. Returns an error, or None on success."""
    try:
        from docx2pdf import convert
    except ImportError:
        return "docx2pdf is not installed"
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            convert(str(src), str(out))
    except Exception as exc:  # noqa: BLE001 -- Word missing surfaces as a COM error
        return f"Microsoft Word is not available ({type(exc).__name__})"
    return None if out.is_file() else "Word produced no file"


def _libreoffice(src: Path, out: Path) -> str | None:
    soffice = shutil.which("soffice") or next((p for p in _SOFFICE if Path(p).is_file()), None)
    if not soffice:
        return "LibreOffice is not installed"
    proc = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out.parent), str(src)],
                          capture_output=True, text=True, timeout=180)
    made = out.parent / (src.stem + ".pdf")
    if proc.returncode != 0 or not made.is_file():
        return f"LibreOffice failed: {(proc.stderr or proc.stdout).strip()[:200]}"
    if made != out:
        made.replace(out)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("output", nargs="?", help="the .pdf to write (default: same name)")
    args = parser.parse_args()

    src = resolve(args.file)
    if not src.is_file():
        return fail(f"no such file: {src}")
    if src.suffix.lower() != ".docx":
        return fail(f"{src.name} is not a .docx")
    out = output_path(args.output or src.with_suffix(".pdf").name)
    errors = []
    for name, convert in (("Word", _word), ("LibreOffice", _libreoffice)):
        error = convert(src.resolve(), out.resolve())
        if error is None:
            print(created(out, converted_with=name))
            return 0
        errors.append(error)
    return fail("; ".join(errors),
                hint=f'read it with read_docx.py "{src.name}", then call create_document with path '
                     f'"{out.name}" and that Markdown (keeps text, tables and images, not the exact layout). '
                     "Tell the user an exact conversion needs Word or LibreOffice.")


if __name__ == "__main__":
    sys.exit(main_wrapper(main))
