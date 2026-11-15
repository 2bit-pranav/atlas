"""The Markdown the model writes, parsed into blocks the writers render."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

# ------------------------------------------------------------- parsing --


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: str | None = None


@dataclass
class Block:
    kind: str                       # heading | para | item | table | code | quote | hr | image
    runs: list[Run] = field(default_factory=list)
    level: int = 0                  # heading level, or list nesting depth
    ordered: bool = False
    number: int = 0
    rows: list[list[list[Run]]] = field(default_factory=list)  # table: first row is the header
    text: str = ""                  # code; image: the path as written
    group: int = 0                  # list items: which top-level list they belong to


def _images(token: Any) -> list[Block]:
    """`![alt](src)` inside a paragraph, as image blocks in order."""
    return [Block("image", [Run(c.content or "")], text=c.attrGet("src") or "")
            for c in token.children or [] if c.type == "image" and c.attrGet("src")]


def _inline(token: Any) -> list[Run]:
    runs: list[Run] = []
    bold = italic = False
    link: str | None = None
    for child in token.children or []:
        t = child.type
        if t == "strong_open":
            bold = True
        elif t == "strong_close":
            bold = False
        elif t == "em_open":
            italic = True
        elif t == "em_close":
            italic = False
        elif t == "link_open":
            link = child.attrGet("href")
        elif t == "link_close":
            link = None
        elif t == "code_inline":
            runs.append(Run(child.content, bold, italic, True, link))
        elif t in ("softbreak", "hardbreak"):
            runs.append(Run("\n" if t == "hardbreak" else " ", bold, italic, False, link))
        elif t == "text" and child.content:
            runs.append(Run(child.content, bold, italic, False, link))
    return runs


_BLOCK_ID = re.compile(r"^\[b\d+\]\s*|\s*\[b\d+(?:, section [\d.]+)?\]\s*$", re.M)
_TABLE_HEAD = re.compile(r"^\[t\d+:[^\n]*$")
_TABLE_ROW = re.compile(r"^r\d+:\s?(.*)$")
_RUN_ROWS = re.compile(r"(?:^|\s)r\d+:\s?")
#: read_docx's heading: `# 2.1 Title [b5]`. The outline number is the reader's, not the title's:
#: copied, "3 Expenses" kept its old number after the sections were reordered (2026-11-14).
#: shortcut: a Title of the form "10 Steps [b1]" loses its "10"; the reader would need to mark its numbers.
_HEADING_NUMBER = re.compile(r"^(#{1,6}\s+)\d{1,2}(?:\.\d{1,2})*\s+(?=.*\[b\d+\]\s*$)")


def without_reader_marks(text: str) -> str:
    """The reader's addresses taken back out of text copied from it.

    read_docx prints `[b2]` before a paragraph, `[b3]` after a heading, and a table
    as a `[t1: table, ...]` line then `r1: a | b | c` rows, so edit_docx can name
    them. Asked to rebuild a document, the model copied that output as it was: the
    new file held the marks as text and the table as lines of prose (3 of 4 runs,
    2026-11-12). Here the marks go, and the rows become a table again.
    """
    out: list[str] = []
    rows: list[str] = []

    def flush() -> None:
        if rows:
            out.append("| " + rows[0] + " |")
            out.append("|" + "---|" * (rows[0].count("|") + 1))
            out.extend("| " + r + " |" for r in rows[1:])
            rows.clear()

    for line in text.split("\n"):
        if _TABLE_HEAD.match(line):
            flush()
            # The model has joined the mark and its rows into one line, `]` dropped (2026-11-14):
            # `[t1: ... r1: Name | City r2: Asha | Pune`.
            if merged := re.search(r"\br1:\s?(.*)$", line):
                rows.extend(r.strip() for r in _RUN_ROWS.split("r1: " + merged.group(1))[1:])
            continue
        if _TABLE_ROW.match(line) and len(_RUN_ROWS.findall(line)) > 1:   # several rows on one line
            rows.extend(r.strip() for r in _RUN_ROWS.split(line)[1:])
            continue
        if (row := _TABLE_ROW.match(line)) and (rows or "|" in line):
            rows.append(row.group(1).strip())
            continue
        flush()
        out.append(_BLOCK_ID.sub("", _HEADING_NUMBER.sub(lambda m: m.group(1), line)))
    flush()
    return "\n".join(out)


def parse_markdown(text: str) -> list[Block]:
    md = MarkdownIt("commonmark").enable("table").enable("strikethrough")
    tokens = md.parse(without_reader_marks(text))
    blocks: list[Block] = []
    lists: list[dict[str, Any]] = []      # stack of {"ordered", "n"}
    quote = 0
    table: Block | None = None
    row: list[list[Run]] | None = None
    in_item_para = False
    group = 0

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "heading_open":
            blocks.append(Block("heading", _inline(tokens[i + 1]), level=int(tok.tag[1])))
            i += 3
            continue
        if t in ("bullet_list_open", "ordered_list_open"):
            start = int(tok.attrGet("start") or 1)
            if not lists:
                group += 1
            lists.append({"ordered": t == "ordered_list_open", "n": start - 1})
        elif t in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif t == "list_item_open":
            lists[-1]["n"] += 1
            in_item_para = True
        elif t == "paragraph_open":
            runs = _inline(tokens[i + 1])
            images = _images(tokens[i + 1])
            if images and not plain(runs).strip():
                # A paragraph that is only an image: the image is the block.
                blocks.extend(images)
                in_item_para = False
                i += 3
                continue
            if lists and in_item_para:
                blocks.append(Block("item", runs, level=len(lists) - 1, group=group,
                                    ordered=lists[-1]["ordered"], number=lists[-1]["n"]))
                in_item_para = False
            else:
                blocks.append(Block("quote" if quote else "para", runs))
            blocks.extend(images)
            i += 3
            continue
        elif t == "blockquote_open":
            quote += 1
        elif t == "blockquote_close":
            quote -= 1
        elif t in ("fence", "code_block"):
            blocks.append(Block("code", text=tok.content.rstrip("\n")))
        elif t == "hr":
            blocks.append(Block("hr"))
        elif t == "table_open":
            table = Block("table")
        elif t == "tr_open":
            row = []
        elif t in ("th_open", "td_open"):
            row.append(_inline(tokens[i + 1]))  # type: ignore[union-attr]
            i += 3
            continue
        elif t == "tr_close" and table is not None and row is not None:
            table.rows.append(row)
            row = None
        elif t == "table_close" and table is not None:
            blocks.append(table)
            table = None
        i += 1
    return blocks


def plain(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


__all__ = ["Block", "Run", "parse_markdown", "plain"]
