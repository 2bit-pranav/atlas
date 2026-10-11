"""TextIngestor: txt, md, json, log, code (spec L4b).

Paragraph-based chunking, deliberately. Docling's chunkers are for documents
with layout; a plain text file has none, and the cheap approach is also the
right one.

Markdown gets slightly better treatment: headings become ``section_path`` so a
search hit can say *where* it found something, which is the difference between
"useful snippet" and "here is a wall of text".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.ingest.contract import CHARS_PER_TOKEN, Chunk, IngestResult

PARSER = "text"
PARSER_VERSION = "1"

#: Split on blank lines, but never below this, so a heading is not its own chunk.
MIN_CHARS = 240
MAX_CHARS = 1600

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_paragraphs(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    chunks: list[str] = []
    buffer = ""
    for block in blocks:
        if not buffer:
            buffer = block
        elif len(buffer) + len(block) + 2 <= MAX_CHARS:
            buffer = f"{buffer}\n\n{block}"
        else:
            chunks.append(buffer)
            buffer = block
    if buffer:
        chunks.append(buffer)
    # A lone short paragraph is still worth keeping; it is often a heading or a
    # caption, which is exactly what a search for it should find.
    return [c for c in chunks if c]


def _markdown_sections(text: str) -> list[tuple[str | None, str]]:
    """Split markdown into (heading path, body)."""
    sections: list[tuple[str | None, list[str]]] = []
    stack: list[str] = []
    current: list[str] = []
    path: str | None = None

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if current:
                sections.append((path, current))
                current = []
            level = len(match.group(1))
            stack = stack[: level - 1]
            stack.append(match.group(2).strip())
            path = " > ".join(stack)
        else:
            current.append(line)
    if current:
        sections.append((path, current))
    return [(p, "\n".join(lines)) for p, lines in sections]


def _stringify_json(value: Any) -> str:
    """Flatten JSON into lines so it can be chunked like prose."""
    lines: list[str] = []

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                walk(item, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{prefix}[{i}]")
        else:
            lines.append(f"{prefix}: {node}")

    walk(value)
    return "\n".join(lines)


def ingest(path: Path, handle: str) -> IngestResult:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".json":
        try:
            body = _stringify_json(json.loads(raw))
            outline_kind = "json"
        except json.JSONDecodeError as exc:
            return IngestResult(
                parser=PARSER, outline={"kind": "json"},
                warnings=[f"could not parse as JSON: {exc}; indexed as text"],
                chunks=[],
            )
    elif suffix in (".md", ".markdown"):
        sections = _markdown_sections(raw)
        chunks: list[Chunk] = []
        for heading, body in sections:
            for part in _split_paragraphs(body):
                location = {"heading": heading} if heading else {}
                chunks.append(
                    Chunk(text=part, section_path=heading, location=location)
                )
        outline = {
            "kind": "markdown",
            "sections": [h for h, _ in sections if h],
            "lines": raw.count("\n") + 1,
        }
        return IngestResult(
            parser=PARSER, outline=outline, chunks=chunks,
        ).reindex()
    else:
        body = raw
        outline_kind = "text"

    chunks = [
        Chunk(text=part, location={"char_start": offset})
        for offset, part in _split_with_offsets(body)
    ]

    if not chunks:
        chunks = [Chunk(text=body.strip()[:MAX_CHARS] or "(empty file)")]

    return IngestResult(
        parser=PARSER,
        outline={
            "kind": outline_kind,
            "chars": len(raw),
            "lines": raw.count("\n") + 1,
            "approx_tokens": max(1, len(raw) // CHARS_PER_TOKEN),
        },
        chunks=chunks,
    ).reindex()


def _split_with_offsets(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    position = 0
    for block in re.split(r"\n\s*\n", text):
        stripped = block.strip()
        if stripped:
            out.append((position + block.find(stripped), stripped))
        position += len(block) + 2
    return out


class TextIngestor:
    name = PARSER
    version = PARSER_VERSION
    suffixes = {".txt", ".md", ".markdown", ".json", ".log", ".csv.txt",
                ".py", ".js", ".ts", ".html", ".yaml", ".yml", ".ini", ".toml"}
    mimetypes = {"text/plain", "text/markdown", "application/json", "text/x-log"}

    def supports(self, filename: str, mime: str | None) -> bool:
        suffix = Path(filename).suffix.lower()
        return suffix in self.suffixes or (mime or "").lower() in self.mimetypes

    def ingest(self, path: Path, handle: str) -> IngestResult:
        return ingest(path, handle)


__all__ = ["MAX_CHARS", "MIN_CHARS", "PARSER", "PARSER_VERSION", "TextIngestor"]
