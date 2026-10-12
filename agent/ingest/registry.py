"""Ingestor registry (spec section 12).

Order matters: the tabular reader is checked first so an ``.xlsx`` never goes
near a document model, and Docling is added in L4c at the end as the fallback
for everything structural.

Registry by MIME *and* suffix, because browsers and Windows disagree about both:
a ``.csv`` often arrives as ``text/plain``, and a ``.xlsx`` sometimes arrives
with no MIME at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent.ingest.contract import IngestResult
from agent.ingest.docling_ingest import DoclingIngestor
from agent.ingest.tabular import TabularIngestor
from agent.ingest.text import TextIngestor


class Ingestor(Protocol):
    name: str
    version: str

    def supports(self, filename: str, mime: str | None) -> bool: ...
    def ingest(self, path: Path, handle: str) -> IngestResult: ...


#: Order is priority, and it is the whole routing rule. Tabular first so an
#: .xlsx never reaches a document model; text next; Docling last, as the
#: fallback for everything structural. DoclingIngestor.supports also refuses
#: the spreadsheet suffixes explicitly, so the two guards agree.
_REGISTRY: list[Ingestor] = [TabularIngestor(), TextIngestor(), DoclingIngestor()]


def register(ingestor: Ingestor) -> None:
    """Append an ingestor. Later entries lose ties, so order is the priority."""
    _REGISTRY.append(ingestor)


def registry() -> list[Ingestor]:
    return list(_REGISTRY)


def pick_ingestor(filename: str, mime: str | None = None) -> Ingestor:
    """The first ingestor that claims this file, else a clear error."""
    for ingestor in _REGISTRY:
        if ingestor.supports(filename, mime):
            return ingestor
    supported = sorted(
        {s for i in _REGISTRY for s in getattr(i, "suffixes", set())}
    )
    raise ValueError(
        f"no ingestor handles {filename!r} (mime={mime!r}). "
        f"Known suffixes: {', '.join(supported)}"
    )


__all__ = ["Ingestor", "pick_ingestor", "register", "registry"]
