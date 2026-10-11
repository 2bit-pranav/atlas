"""The one contract every ingestor returns (spec sections 11.3 and 12).

Keeping this small and uniform is the point: Docling, the tabular reader and
the text reader differ wildly in what they do, but the rest of Atlas only ever
sees an ``IngestResult``. Adding a format means adding an ingestor, not
touching the pipeline.

**Routing is by output kind, never by content** (section 11.3). An ingestor
declares what it produced -- tables go to DuckDB, text/outline go to SQLite --
and nothing downstream sniffs the file to guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Roughly four characters per token for English prose. Good enough for
#: budgeting; ``/tokenize`` on llama-server is the accurate path when it
#: matters (S6), and L6 switches to it.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def sanitize_identifier(name: str) -> str:
    """Make a table/view name safe for DuckDB and for the model to type.

    Handles are ``f1``; sheet names come from the file and can contain spaces,
    punctuation or start with a digit, so they are quoted and trimmed.
    """
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name)).strip("_").lower()
    if not cleaned:
        cleaned = "col"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned[:60]


@dataclass
class Chunk:
    """One retrievable span. ``kind`` decides how ``search`` treats it."""

    text: str
    kind: str = "text"                 # text | table_text | schema | caption
    section_path: str | None = None
    location: dict[str, Any] = field(default_factory=dict)
    idx: int = 0

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def to_row(self, chunk_id: str, attachment_id: str, extraction_id: str,
               created_at: int) -> tuple:
        import json

        return (
            chunk_id, attachment_id, extraction_id, "chat", self.idx, self.kind,
            self.section_path,
            json.dumps(self.location, ensure_ascii=False) if self.location else None,
            self.text, self.tokens, created_at,
        )


@dataclass
class TableSpec:
    """A table to register in the chat's DuckDB file.

    ``name`` is the table name; ``sheet`` is the source sheet, which becomes the
    ``_sheet`` column of the unified view.
    """

    name: str
    sheet: str | None
    rows: int
    columns: list[str]
    #: Rows as a list of tuples, or a pandas DataFrame, resolved by the store.
    data: Any = None
    #: True when this sheet's header matched the group used for the unified view.
    in_unified: bool = False


@dataclass
class IngestResult:
    """What every ingestor returns."""

    parser: str                          # docling | tabular | text
    outline: dict[str, Any] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    tables: list[TableSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0
    #: Set when the parser wants the raw document saved for re-chunking
    #: (``doc_json_path``), so a chunker change never re-parses (section 12).
    doc_json_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def token_count(self) -> int:
        return sum(c.tokens for c in self.chunks)

    def reindex(self) -> "IngestResult":
        """Renumber chunks so ``idx`` is dense and ordered after any filtering."""
        for i, chunk in enumerate(self.chunks):
            chunk.idx = i
        return self


__all__ = [
    "CHARS_PER_TOKEN",
    "Chunk",
    "IngestResult",
    "TableSpec",
    "estimate_tokens",
    "sanitize_identifier",
]
