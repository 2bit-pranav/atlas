"""DoclingIngestor: PDF, DOCX, PPTX, HTML and images (spec L4c).

The document pipeline. Everything structural comes from Docling, and the
output is routed by *kind*, never sniffed (section 11.3): prose and headings
become chunks for search, tables become DuckDB tables.

**Measured on this machine (i5, CPU only, no CUDA), warm** -- the numbers that
decided `standard` as the default:

===========================  =======  =========  ==============
document                     pages   convert    per page
===========================  =======  =========  ==============
prose only, no tables            2     4.0s      ~2.4s
one 24-row table per page        3    26.3s      ~8.8s
real paper (exp1.pdf)            6    19.1s      ~3.2s
real paper (exp2.pdf)            9    26.7s      ~3.0s
===========================  =======  =========  ==============

First use is 394s and means nothing: that is `docling-layout-heron` (328 MB)
and `docling-models` (342 MB) downloading, plus RapidOCR's ONNX models. Warm
converter construction is 0.15-0.41s. A document timeout is set because of it.

**Docling overlaps tables rather than splitting them, and the totals show it.**
On a 3-page PDF whose pages each hold one 24-row table, Docling returned five
frames: ``Region-00..23`` on page 1 *plus* ``Region-00..07`` again, then
``Region-08..23`` and ``Region-00..17`` on page 2, then ``Region-18..23``. The
frame lengths sum to 72, which is exactly the source row count -- so a naive
concatenation produces the *right number of rows* and a **SUM 33% high**. That
is the most dangerous shape of bug this project has met, and it is why
:func:`merge_fragments` unions by row identity rather than concatenating, and
why the test asserts on a SUM rather than a count.

Note the first attempt at this was wrong in the other direction: a
page-adjacency rule fused three genuinely separate tables into one 72-row
table. The page number alone says nothing reliable -- two frames of one table
can share a page -- so frames are grouped per page and unioned by content.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agent.ingest.contract import Chunk, IngestResult, TableSpec, sanitize_identifier
from agent.ingest.tabular import coerce_types

logger = logging.getLogger(__name__)

PARSER = "docling"
PARSER_VERSION = "1"

#: Formulas, superscripts and layout coordinates are noise in a search index.
TABLE_CELL_MAX = 200


def _format_cells(frame: Any, max_cells: int = TABLE_CELL_MAX) -> str:
    """A table as pipe-delimited text.

    Rendered this way rather than as CSV because the result is read by a model
    and by ``search``: pipes keep multi-line cells readable and cost one token
    per delimiter, where a quoted CSV field is mostly escape characters.
    """
    if frame is None or getattr(frame, "empty", True):
        return ""
    columns = [str(c) for c in frame.columns]
    lines = [" | ".join(columns)]
    for _, row in frame.iterrows():
        cells = ["" if v is None else str(v).replace("\n", " ") for v in row.tolist()]
        lines.append(" | ".join(cells))
        if len(lines) > max_cells:
            lines.append(f"... (truncated at {max_cells} rows)")
            break
    return "\n".join(lines)


def _page_of(item: Any, fallback: int) -> int:
    """1-based page number for a docling item, best effort.

    Docling's provenance carries the page, but not every item type populates
    it, so an unlocated fragment inherits the page it follows. Getting this
    wrong costs a slightly imprecise ``p.4`` in a search hit; getting the
    *merge* wrong costs a wrong SUM, which is why only the merge is strict.
    """
    prov = getattr(item, "prov", None) or []
    for p in prov:
        page = getattr(p, "page_no", None)
        if isinstance(page, int) and page > 0:
            return page
    return fallback


def _row_key(row: dict[str, Any]) -> tuple:
    """A row's identity, for deciding whether two fragments overlap.

    The first column is the discriminator in practice -- a table's row label
    or its leftmost value -- and it is what a reader would compare. Falling
    back to the whole row keeps the comparison working for a table whose first
    column is empty or duplicated.
    """
    values = [("" if v is None else str(v).strip()) for v in row.values()]
    return (values[0],) if values and values[0] else tuple(values)


def _union_by_key(existing: Any, incoming: Any) -> Any:
    """Append only the rows of ``incoming`` whose key is not already present.

    Docling does not split a table cleanly. Measured on a 3-page PDF whose
    pages each hold one 24-row table, it returned *five* frames:

        page 1  Region-00..23   (the whole table)   +  Region-00..07  (repeat)
        page 2  Region-08..23                    +  Region-00..17
        page 3  Region-18..23

    so the frames overlap by arbitrary amounts and the sum of their lengths
    (72) coincidentally equals the source (72) while the *content* is nothing
    like 72 distinct rows. Concatenating them produced a SUM 33% high. Taking
    the union by row identity is the only operation that is right on this
    input, and it also means a frame wholly contained in another is absorbed
    silently rather than counted twice.

    Genuine duplicate rows *within* one table are preserved: dedup is by
    position against keys already seen, so a table with two equal rows keeps
    both. Losing one would turn an overcount into a silent undercount, which
    is harder to notice because the error points the other way.
    """
    import pandas as pd

    seen = {_row_key(r) for r in existing.to_dict(orient="records")}
    added = [
        r for r in incoming.to_dict(orient="records")
        if _row_key(r) not in seen
    ]
    for row in added:
        seen.add(_row_key(row))
    if not added:
        return existing
    return pd.concat(
        [existing, pd.DataFrame(added, columns=list(incoming.columns))],
        ignore_index=True,
    )


def merge_fragments(frames: list[tuple[int, Any]]) -> list[tuple[list[int], Any]]:
    """Re-join the overlapping frames Docling returns for one table.

    ``frames`` is ``(page_no, dataframe)`` in document order. Frames are
    grouped by page and then unioned by row identity, because a page is the
    only reliable boundary Docling gives us: two frames on the same page with
    overlapping rows are the same table seen twice, and merging across pages
    would fuse genuinely separate tables (a document with one table per page
    is the common case, and it looks identical to a table that spans pages).

    Every merge is reported by :func:`_describe_merges`, so a table that
    arrived whole and a table that was reassembled are never presented the
    same way.
    """
    by_page: dict[int, list[Any]] = {}
    page_order: list[int] = []
    for page, frame in frames:
        if frame is None or getattr(frame, "empty", True):
            continue
        if page not in by_page:
            by_page[page] = []
            page_order.append(page)
        by_page[page].append(frame)

    merged: list[tuple[list[int], Any]] = []
    for page in page_order:
        group = by_page[page][0]
        seen_rows = 1
        for extra in by_page[page][1:]:
            before = len(group)
            group = _union_by_key(group, extra)
            if len(group) != before:
                seen_rows += 1
        merged.append(([page] * seen_rows, group))
    return merged


def _describe_merges(merged: list[tuple[list[int], Any]]) -> list[str]:
    notes: list[str] = []
    for pages, frame in merged:
        if len(pages) <= 1:
            continue
        if len(set(pages)) == 1:
            where = f"page {pages[0]}"
        elif pages == list(range(min(pages), max(pages) + 1)):
            where = f"pages {pages[0]}-{pages[-1]}"
        else:
            where = f"pages {', '.join(str(p) for p in sorted(set(pages)))}"
        notes.append(
            f"a table on {where} was split by layout analysis into {len(pages)} "
            f"fragments and rejoined into one table of {len(frame)} rows"
        )
    return notes


def _document_outline(
    doc: Any, path: Path, pipeline: str, headings: list[tuple[str, int]]
) -> dict[str, Any]:
    """The document's structure, taken from the headings the chunker used.

    Built from the same list that assigned ``section_path``, never from
    ``doc.texts`` directly. Those two can disagree -- the layout model's own
    labels are exactly what was wrong here -- and an outline that omits a
    section while the chunk store has it is the worst outcome available: the
    model lists the structure, sees the section missing, and reports its
    absence as fact. Measured, that is how a document with a Step 6 came to be
    described as ending at Step 5.

    Every heading is listed, at every depth, in document order. Taking only the
    *first* element of each ``section_path`` was tried and loses anything
    nested, which is how Steps 3 and 4 vanished the first time round -- the
    same bug, one level down. Depth is carried so a caller can indent.
    """
    pages = getattr(doc, "pages", {}) or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text, depth in headings:
        key = text.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"text": text[:120], "depth": depth})

    return {
        "kind": "document",
        "pipeline": pipeline,
        "pages": len(pages),
        "headings": [h["text"] for h in out[:80]],
        "structure": out[:80],
        "heading_count": len(out),
        "bytes": path.stat().st_size,
    }


#: A short line that looks like a heading even when the layout model disagreed.
#: Measured on a real lab document, Docling's layout stage labelled only two of
#: the six "Step N:" headings as ``section_header``; the other four came back as
#: plain ``text``. They were extracted perfectly -- all six were in the chunks
#: -- but they never became a ``section_path`` and never appeared in
#: ``outline.headings``. The model then listed the document's structure, saw
#: no Step 6, and told the user the document ended at Step 5. It was faithfully
#: reporting an outline we built from the wrong signal.
#:
#: The test is deliberately narrow: a short line, with no terminal sentence
#: punctuation, that matches a structural pattern. Being generous here would
#: promote ordinary prose into the outline, which is its own kind of lie.
_HEADING_LIKE = re.compile(
    r"""^\s*(?:
          (?:step|stage|phase|part|chapter|section|lesson|appendix)\s*\d+\b
        | \d+\.\s+\S
        | [IVXLC]+\.\s+\S
        | [A-Z][\w\s'&/()-]{2,60}:\s*$
        )""",
    re.IGNORECASE | re.VERBOSE,
)

#: Above this, a line is prose however it is punctuated.
HEADING_MAX_CHARS = 90


def _looks_like_heading(text: str, label: str) -> bool:
    """True when a short, unpunctuated line is a heading whatever Docling said."""
    stripped = text.strip()
    if not stripped or len(stripped) > HEADING_MAX_CHARS:
        return False
    if label in ("title", "section_header"):
        return True
    if stripped.endswith((".", "!", "?", ",", ";")):
        return False
    return bool(_HEADING_LIKE.match(stripped))


def _chunks_from_document(
    doc: Any, page_hint: dict[int, int]
) -> tuple[list[Chunk], list[tuple[str, int]]]:
    """Prose chunks, one per text item, carrying its page and its heading.

    Docling's own hybrid chunkers are built for this, but they merge across
    element boundaries and lose the page number, and a search hit that cannot
    say *where* it found something is much less useful than one that can.
    Splitting per text element keeps the page and the heading, and the element
    texts are already paragraph-sized.
    """
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    #: Every heading in document order, at every depth. The outline is built
    #: from this rather than from the chunks' section_path, because a heading
    #: nested under another (a sub-step under a Step) is not the *first*
    #: element of any path and would silently vanish from the outline -- which
    #: is the same class of bug as the one being fixed, one level down.
    headings: list[tuple[str, int]] = []

    for item in getattr(doc, "texts", None) or []:
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        label = str(getattr(item, "label", ""))
        page = _page_of(item, 1)

        if _looks_like_heading(text, label):
            try:
                depth = int(doc._get_heading_level(item) or 0) + 1
            except Exception:  # noqa: BLE001 - private API, may move
                depth = 1
            # A promoted heading that Docling called plain text has no
            # hierarchy, so it must not push the real ones deeper or every
            # later section_path inherits a level it never had.
            if label not in ("title", "section_header"):
                depth = 1
            heading_stack = [(d, t) for d, t in heading_stack if d < depth]
            heading_stack.append((depth, text[:120]))
            if not any(t == text[:120] for _, t in heading_stack[:-1]):
                headings.append((text[:120], depth))
            path = " > ".join(t for _, t in heading_stack)
            chunks.append(Chunk(
                text=text,
                kind="text",
                section_path=path or None,
                location={"page": page, "label": label,
                          "promoted_heading": label not in ("title", "section_header")},
            ))
            continue

        if label in ("page_header", "page_footer"):
            # Repeated on every page; indexing it would fill search with noise
            # that matches almost any query.
            continue

        section = " > ".join(t for _, t in heading_stack) or None
        chunks.append(Chunk(
            text=text,
            kind="text",
            section_path=section,
            location={"page": page, "label": label},
        ))
    return chunks, headings


def ingest(path: Path, handle: str, settings: dict[str, Any] | None = None) -> IngestResult:
    settings = settings or {}
    docling_settings = (settings.get("ingest") or {}).get("docling") or {}
    pipeline_name = str(docling_settings.get("pipeline", "standard")).lower()
    if pipeline_name not in ("standard", "vlm", "auto"):
        pipeline_name = "standard"

    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    def _map_format(suffix: str) -> InputFormat | None:
        return {
            ".pdf": InputFormat.PDF,
            ".docx": InputFormat.DOCX,
            ".pptx": InputFormat.PPTX,
            ".html": InputFormat.HTML,
            ".htm": InputFormat.HTML,
            ".md": InputFormat.MD,
            ".csv": InputFormat.CSV,
            ".xlsx": InputFormat.XLSX,
            ".png": InputFormat.IMAGE,
            ".jpg": InputFormat.IMAGE,
            ".jpeg": InputFormat.IMAGE,
            ".tif": InputFormat.IMAGE,
            ".tiff": InputFormat.IMAGE,
            ".bmp": InputFormat.IMAGE,
            ".webp": InputFormat.IMAGE,
        }.get(suffix)

    suffix = path.suffix.lower()
    fmt = _map_format(suffix)
    if fmt is None:
        raise ValueError(f"docling has no reader for {suffix!r}")

    warnings: list[str] = []
    used_pipeline = pipeline_name
    converter = _build_converter(fmt, pipeline_name, warnings)
    if converter is None:
        used_pipeline = "standard"
        converter = _build_converter(fmt, "standard", warnings)

    result = converter.convert(str(path))
    doc = result.document
    if not used_pipeline:
        used_pipeline = "standard"

    # ---------------------------------------------------------- tables ----
    raw_tables: list[tuple[int, Any]] = []
    for table in getattr(doc, "tables", []) or []:
        try:
            frame = table.export_to_dataframe(doc=doc)
        except TypeError:
            # Older signature without the `doc` argument (deprecated in 2.137).
            frame = table.export_to_dataframe()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"table could not be converted: {type(exc).__name__}: {exc}")
            continue
        raw_tables.append((_page_of(table, 1), frame))

    tables: list[TableSpec] = []
    chunks: list[Chunk] = []
    total_rows = 0
    for index, (pages, frame) in enumerate(merge_fragments(raw_tables)):
        columns = [str(c) for c in frame.columns]
        sheet = f"table_{index + 1}" + (f"_p{pages[0]}" if pages else "")
        table_name = f"{handle}_{sanitize_identifier(sheet)}"
        rows = frame.to_dict(orient="records")
        rows, type_warnings = coerce_types(rows, table_name)
        warnings.extend(type_warnings)
        total_rows += len(rows)
        tables.append(TableSpec(
            name=table_name, sheet=sheet, rows=len(rows), columns=columns,
            data=rows, in_unified=False,
        ))
        rendered = _format_cells(frame)
        if rendered:
            chunks.append(Chunk(
                text=f"Table {table_name} on page {pages[0] if pages else '?'}\n{rendered}",
                kind="table_text",
                section_path=None,
                location={"page": pages[0] if pages else None, "table": table_name,
                          "rows": len(rows), "columns": columns},
            ))
        chunks.append(Chunk(
            text=f"Table {table_name} columns: {' | '.join(columns)}",
            kind="schema",
            location={"table": table_name, "page": pages[0] if pages else None},
        ))

    warnings.extend(_describe_merges(merge_fragments(raw_tables)))

    # ----------------------------------------------------------- prose ----
    page_hint = {i: i + 1 for i in range(len(getattr(doc, "pages", {}) or {}))}
    prose_chunks, headings = _chunks_from_document(doc, page_hint)
    chunks.extend(prose_chunks)
    chunks.sort(key=lambda c: ((c.location or {}).get("page") or 0, c.idx))

    outline = _document_outline(doc, path, used_pipeline, headings)
    outline["tables"] = [{"table": t.name, "rows": t.rows, "columns": t.columns} for t in tables]
    outline["total_rows"] = total_rows

    if not chunks:
        warnings.append("no text or tables were extracted; the file may be a scan")

    return IngestResult(
        parser=PARSER,
        outline=outline,
        chunks=chunks,
        tables=tables,
        warnings=warnings,
        page_count=len(getattr(doc, "pages", {}) or {}),
        extra={"pipeline": used_pipeline},
    ).reindex()


def _build_converter(fmt: Any, pipeline_name: str, warnings: list[str]) -> Any:
    """Build a converter, degrading to `standard` if `vlm` cannot be built.

    `vlm` needs a second llama-server (Granite-Docling) and that server may not
    be running. Rather than failing the whole ingest, fall back to `standard`
    and say so in the warnings -- the document still parses, and the model is
    told the quality is the fallback's.
    """
    from docling.document_converter import DocumentConverter, PdfFormatOption

    if pipeline_name in ("vlm", "auto"):
        try:
            options = _vlm_options()
            if options is not None:
                return DocumentConverter(
                    format_options={fmt: PdfFormatOption(pipeline_options=options)}
                )
            warnings.append(
                "ingest.docling.pipeline is 'vlm' or 'auto' but no VLM server is "
                "configured; used 'standard' instead"
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"VLM pipeline unavailable ({type(exc).__name__}: {exc}); used 'standard'")

    if pipeline_name == "auto":
        # 'auto' means standard first, vlm only for pages with no text layer.
        # The per-page escalation is L4e; until the VLM server exists, standard
        # is the whole of 'auto'.
        return DocumentConverter()

    return DocumentConverter()


def _vlm_options() -> Any:
    """Build ApiVlmOptions for a locally served Granite-Docling, or None.

    Returns None rather than raising when the model is not configured, so the
    caller can fall back instead of failing the document.
    """
    import json
    from pathlib import Path as _Path

    raw = os.environ.get("ATLAS_SETTINGS", "settings.json")
    try:
        settings = json.loads(_Path(raw).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    vlm = ((settings.get("ingest") or {}).get("vlm")) or {}
    model_path = str(vlm.get("model_path") or "").strip()
    if not model_path:
        return None
    if not _Path(model_path).exists():
        return None

    port = (settings.get("ports") or {}).get("ingest_vlm", 8081)
    from docling.pipeline.vlm_pipeline import ApiVlmOptions

    return ApiVlmOptions(
        url=f"http://127.0.0.1:{port}/v1/chat/completions",
        timeout=float(vlm.get("timeout_s", 300)),
        temperature=0.0,
    )


class DoclingIngestor:
    """Registry-shaped wrapper, like every other ingestor."""

    name = PARSER
    version = PARSER_VERSION
    suffixes = {
        ".pdf", ".docx", ".pptx", ".html", ".htm",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    }
    mimetypes = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-word",
        "text/html",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "image/webp",
    }

    def supports(self, filename: str, mime: str | None) -> bool:
        suffix = Path(filename).suffix.lower()
        # An .xlsx is TabularIngestor's, always: a spreadsheet needs no
        # document model, and this ingestor is registered last.
        if suffix in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".tab", ".md"):
            return False
        return suffix in self.suffixes or (mime or "").lower() in self.mimetypes

    def ingest(self, path: Path, handle: str, settings: dict[str, Any] | None = None) -> IngestResult:
        return ingest(path, handle, settings)


__all__ = [
    "DoclingIngestor",
    "PARSER",
    "PARSER_VERSION",
    "merge_fragments",
]
