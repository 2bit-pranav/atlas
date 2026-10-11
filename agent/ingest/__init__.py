"""L4: ingestion - upload, parse, index.

    attachments.py  persistence (attachments, extractions, chunks, FTS search)
    contract.py     the IngestResult every ingestor returns
    duckstore.py    per-chat DuckDB: tables, unified views, quality warnings
    tabular.py      TabularIngestor  (XLSX/CSV/TSV)
    text.py         TextIngestor     (txt/md/json/log/code)
    registry.py     suffix/MIME -> ingestor
    worker.py       the single background worker and the service around it

Docling lands in ``docling.py`` and registers itself last (L4c); embeddings
land in ``embedding.py`` as the stage-2 half of readiness (L4d).
"""

from agent.ingest.attachments import AttachmentStore
from agent.ingest.contract import Chunk, IngestResult, TableSpec
from agent.ingest.duckstore import DuckStore
from agent.ingest.registry import pick_ingestor, register, registry
from agent.ingest.tabular import TabularIngestor
from agent.ingest.text import TextIngestor
from agent.ingest.worker import IngestService, IngestWorker, ingest_one

__all__ = [
    "AttachmentStore",
    "Chunk",
    "DuckStore",
    "IngestResult",
    "IngestService",
    "IngestWorker",
    "TableSpec",
    "TabularIngestor",
    "TextIngestor",
    "ingest_one",
    "pick_ingestor",
    "register",
    "registry",
]
