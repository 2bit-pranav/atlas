#!/usr/bin/env python3
"""
rotate_pdf.py — Rotate pages in a PDF file.

Usage:
    python rotate_pdf.py <input_pdf> <output_pdf> [angle] [pages]

Arguments:
    input_pdf   Absolute path to the source PDF.
    output_pdf  Absolute path for the rotated output PDF.
    angle       Rotation in degrees clockwise: 90, 180, or 270 (default: 90).
    pages       Comma-separated 1-based page numbers to rotate, or "all" (default: all).

Examples:
    python rotate_pdf.py /path/to/input.pdf /path/to/rotated.pdf 90 all
    python rotate_pdf.py /path/to/input.pdf /path/to/rotated.pdf 180 1,3,5
"""

import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: rotate_pdf.py <input_pdf> <output_pdf> [angle=90] [pages=all]",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = Path(sys.argv[1]).expanduser().resolve()
    output_path = Path(sys.argv[2]).expanduser().resolve()
    angle = int(sys.argv[3]) if len(sys.argv) > 3 else 90
    pages_arg = sys.argv[4] if len(sys.argv) > 4 else "all"

    if not input_path.is_file():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if angle not in (90, 180, 270):
        print(f"[ERROR] Angle must be 90, 180, or 270. Got: {angle}", file=sys.stderr)
        sys.exit(1)

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("[ERROR] pypdf is not installed. Run: pip install pypdf", file=sys.stderr)
        sys.exit(1)

    reader = PdfReader(str(input_path))
    total_pages = len(reader.pages)

    # Determine which page indices (0-based) to rotate
    if pages_arg.strip().lower() == "all":
        target_indices = set(range(total_pages))
    else:
        target_indices = set()
        for token in pages_arg.split(","):
            token = token.strip()
            if token.isdigit():
                idx = int(token) - 1  # convert 1-based → 0-based
                if 0 <= idx < total_pages:
                    target_indices.add(idx)
                else:
                    print(f"[WARNING] Page {token} out of range (document has {total_pages} pages), skipping.")

    if not target_indices:
        print("[ERROR] No valid pages selected for rotation.", file=sys.stderr)
        sys.exit(1)

    writer = PdfWriter()
    rotated_count = 0
    for i, page in enumerate(reader.pages):
        if i in target_indices:
            page.rotate(angle)
            rotated_count += 1
        writer.add_page(page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)

    size = output_path.stat().st_size
    print(
        f"SUCCESS: Rotated {rotated_count}/{total_pages} page(s) by {angle} degrees -> '{output_path}' ({size} bytes)"
    )


if __name__ == "__main__":
    main()
