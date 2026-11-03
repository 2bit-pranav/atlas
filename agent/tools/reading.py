"""Reading files: `read_text` and `read_image`, in place of the harness `read`.

The harness `read` had two faults the document benchmark measured
(decisions.md, 2026-11-03). It had no output cap: a 3,000-line log came back
whole, 70k tokens against a 32k context, and the turn failed. And its name
invited it on every file: a small model called `read` on PDFs again and again.
Typed names say what each reads, and every result is capped, says what it
left out, and gives the exact next call.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from strands import tool

#: About 1,500 tokens, the same budget as the skill readers (skills/_shared.py).
MAX_CHARS = 6000
#: A longer line is cut, so one minified line cannot take the whole budget.
MAX_LINE = 400
IMAGES = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp"}
MAX_IMAGE = 10 * 1024 * 1024


def _failed(message: str) -> dict[str, Any]:
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


def _decode(data: bytes) -> str | None:
    """Text, or None for a binary file."""
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _line(n: int, text: str) -> str:
    if len(text) > MAX_LINE:
        text = text[:MAX_LINE] + f" [... line cut, {len(text):,} chars]"
    return f"{n:>6}\t{text}"


def _window(name: str, lines: list[str], start: int, end: int | None) -> str:
    total = len(lines)
    if total == 0:
        return f"{name} is empty."
    start = max(1, start)
    if start > total:
        return f"{name} has {total} lines; start_line {start} is past the end."
    last = min(end or total, total)
    out, size = [], 0
    for n in range(start, last + 1):
        row = _line(n, lines[n - 1])
        if out and size + len(row) > MAX_CHARS:
            break
        out.append(row)
        size += len(row) + 1
    shown = start + len(out) - 1
    head = f"{name}: lines {start}-{shown} of {total}"
    if shown < total:
        # Without this the model read the first window and answered "the log has no errors".
        head += (f". {total - shown} more lines are NOT shown; do not conclude something is absent. "
                 f"Next: read_text(path=\"{name}\", start_line={shown + 1}), or find a line with "
                 f"read_text(path=\"{name}\", search=\"words\")")
    return head + "\n" + "\n".join(out)


def _search(name: str, lines: list[str], query: str) -> str:
    """Lines holding the most of the query's words (case ignored), in file order.

    Words, not the phrase: "sensor K7 calibration constant" must find
    "The calibration constant for sensor K7 is ..." (decisions.md, 2026-11-03).
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return _window(name, lines, 1, None)
    scored = [(sum(w in line.lower() for w in set(words)), n) for n, line in enumerate(lines, 1)]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return f"No line in {name} contains any of: {', '.join(words)}. It has {len(lines)} lines."
    hits = [n for s, n in scored if s == best]
    out, size = [], 0
    for n in hits:
        row = _line(n, lines[n - 1])
        if out and size + len(row) > MAX_CHARS:
            break
        out.append(row)
        size += len(row) + 1
    match = "all of" if best == len(set(words)) else f"{best} of the {len(set(words))} words"
    head = f"{name}: {len(hits)} line{'s' * (len(hits) != 1)} with {match} \"{query}\""
    if len(out) < len(hits):
        head += f"; showing the first {len(out)}. Add a word to narrow it"
    return head + (f". Read around one with read_text(path=\"{name}\", start_line=N)\n"
                   + "\n".join(out))


def read_tools(resolve: Callable[[str], Path], shown: Callable[[Path], str],
               reader: Callable[[str], str | None], vision: bool) -> list[Any]:
    """The two tools, for one chat.

    `resolve` places a path as every file tool does (`placement.locate`);
    `reader` gives the skill command for a pdf/docx/xlsx (`readers.py`).
    """

    def _missing(target: Path) -> dict[str, Any]:
        return _failed(f"no file {target.name} at {shown(target)}. Name a file in your workspace, "
                       "or give its full path.")

    @tool(name="read_text")
    def read_text(path: str, start_line: int = 1, end_line: int = 0, search: str = "") -> Any:
        """Read a text file (.txt, .md, .csv, .log, .json, code): numbered lines, capped near 1,500 tokens.

        Not for .pdf/.docx/.xlsx (use the command given with the file) or images (use read_image).
        Long files: read in steps with start_line, or find lines with search, e.g. search="error timeout".

        Args:
            path: File name in your workspace, or its full path.
            start_line: First line to show (1-based).
            end_line: Last line to show; 0 for as many as fit.
            search: Words to find; returns the lines holding the most of them, with line numbers.
        """
        target = resolve(path)
        if target.suffix.lower() in IMAGES:
            return _failed(f"{target.name} is an image. Use read_image(path=\"{target.name}\").")
        if (command := reader(path)) is not None:
            return _failed(f"{target.name} is not a text file. Read it with: {command} "
                           "(to merge, split, combine or convert it, load its skill first)")
        if not target.is_file():
            return _missing(target)
        text = _decode(target.read_bytes())
        if text is None:
            return _failed(f"{target.name} is a binary file, not text; read_text cannot show it.")
        lines = text.splitlines()
        if search.strip():
            return _search(target.name, lines, search)
        return _window(target.name, lines, start_line, end_line or None)

    @tool(name="read_image")
    def read_image(path: str) -> Any:
        """Look at an image file (.png, .jpg, .jpeg, .gif, .webp).

        Args:
            path: File name in your workspace, or its full path.
        """
        target = resolve(path)
        fmt = IMAGES.get(target.suffix.lower())
        if fmt is None:
            return _failed(f"{target.name} is not an image (.png, .jpg, .jpeg, .gif, .webp). "
                           "Use read_text for text files.")
        if not vision:
            return _failed("this model cannot see images.")
        if not target.is_file():
            return _missing(target)
        if target.stat().st_size > MAX_IMAGE:
            return _failed(f"{target.name} is larger than {MAX_IMAGE // 1024 // 1024} MB.")
        return {"status": "success", "content": [{"image": {"format": fmt, "source": {"bytes": target.read_bytes()}}}]}

    return [read_text, read_image]


__all__ = ["MAX_CHARS", "read_tools"]
