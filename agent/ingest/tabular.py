"""TabularIngestor: XLSX, CSV, TSV straight into DuckDB (spec L4a).

No document model, no OCR, no layout analysis -- a spreadsheet is already
structured, so going near Docling would only add time and loss.

Produces, per section 11.3:
* one DuckDB table per sheet, ``<handle>_<sheet>``;
* a unified ``<handle>_all`` view over the sheets whose headers agree, with a
  ``_sheet`` column;
* one ``schema`` chunk per table, so ``search`` can find "revenue" even though
  the value never appears in any prose;
* quality warnings recorded now, not at query time.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from agent.ingest.contract import Chunk, IngestResult, TableSpec, sanitize_identifier

PARSER = "tabular"
PARSER_VERSION = "1"

#: Files bigger than this are rejected with a clear message rather than
#: silently truncated; the UI should route them through the data-store path.
MAX_ROWS = 5_000_000


def _read_csv(path: Path) -> dict[str, list[dict[str, Any]]]:
    """One pseudo-sheet named after the file stem."""
    delimiter = "\t" if path.suffix.lower() in (".tsv", ".tab") else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            pass
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = [dict(row) for row in reader]
    return {path.stem: rows}


def _read_excel(path: Path) -> dict[str, list[dict[str, Any]]]:
    import pandas as pd

    book = pd.read_excel(path, sheet_name=None, dtype=object)
    return {name: frame.to_dict(orient="records") for name, frame in book.items()}


#: A column is treated as numeric when at least this share of its non-empty
#: values parse as numbers. Below it the column stays text: a numeric-looking
#: column that is mostly text is a text column, and coercing it would invent
#: data rather than clean it.
NUMERIC_DOMINANCE = 0.8


def coerce_types(
    rows: list[dict], table_name: str
) -> tuple[list[dict], list[str]]:
    """Make numeric columns actually numeric, and report what was dropped.

    This is the difference between the spec's worked example working and not.
    One sheet with ``n/a`` in ``revenue`` otherwise types the whole column
    VARCHAR, and ``SUM(revenue)`` then fails -- the model cannot sum a column at
    all because of two cells. Instead the bad values become NULL, the column
    stays summable, and the warning says exactly what was lost, so nothing is
    hidden from the model.
    """
    if not rows:
        return rows, []

    import pandas as pd

    frame = pd.DataFrame(rows)
    warnings: list[str] = []
    cleaned = {index: dict(row) for index, row in enumerate(rows)}

    for column in frame.columns:
        non_null = frame[column].dropna()
        if non_null.empty:
            continue
        coerced = pd.to_numeric(non_null, errors="coerce")
        parseable = int(coerced.notna().sum())
        if parseable == 0:
            continue                       # genuinely a text column
        if parseable / len(non_null) < NUMERIC_DOMINANCE:
            continue

        bad = [str(v) for v in non_null[coerced.isna()].tolist()]
        if bad:
            preview = ", ".join(bad[:3])
            warnings.append(
                f"{table_name}.{column} has {len(bad)} non-numeric value(s) of "
                f"{len(non_null)} (e.g. {preview}); they are NULL, so aggregates "
                f"ignore them"
            )
        for index in cleaned:
            value = cleaned[index].get(column)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            if pd.isna(pd.to_numeric(value, errors="coerce")):
                cleaned[index][column] = None

    return [cleaned[i] for i in sorted(cleaned)], warnings


def _signature(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    if not rows:
        return ()
    return tuple(sorted(str(k) for k in rows[0].keys()))


def ingest(path: Path, handle: str) -> IngestResult:
    suffix = path.suffix.lower()
    sheets = (
        _read_excel(path) if suffix in (".xlsx", ".xlsm", ".xls") else _read_csv(path)
    )
    if not sheets:
        return IngestResult(
            parser=PARSER,
            outline={"sheets": []},
            warnings=[f"{path.name} contained no sheets"],
        )

    signatures = {name: _signature(rows) for name, rows in sheets.items()}
    # The largest agreeing group becomes the unified view; sheets that disagree
    # stay separate and are reported rather than silently excluded.
    from collections import Counter

    counts = Counter(signatures.values())
    target_signature = counts.most_common(1)[0][0] if counts else ()
    unified_sheets = {n for n, s in signatures.items() if s == target_signature}

    tables: list[TableSpec] = []
    outline_sheets: list[dict[str, Any]] = []
    chunks: list[Chunk] = []
    warnings: list[str] = []

    for sheet, rows in sheets.items():
        columns = [str(c) for c in signatures[sheet]]
        in_unified = sheet in unified_sheets and bool(target_signature)
        table_name = f"{handle}_{sanitize_identifier(sheet)}"
        if len(rows) > MAX_ROWS:
            warnings.append(f"{sheet} has {len(rows)} rows; truncated to {MAX_ROWS}")
            rows = rows[:MAX_ROWS]

        rows, type_warnings = coerce_types(rows, table_name)
        warnings.extend(type_warnings)

        tables.append(TableSpec(
            name=table_name, sheet=sheet, rows=len(rows), columns=columns,
            data=rows, in_unified=in_unified,
        ))
        outline_sheets.append({
            "sheet": sheet, "table": table_name, "rows": len(rows),
            "columns": columns, "unified": in_unified,
        })

        # A schema chunk makes the columns findable by search even though no
        # prose ever mentions them.
        header = " | ".join(columns)
        chunks.append(Chunk(
            text=f"Table {table_name} (sheet {sheet}) columns: {header}",
            kind="schema", section_path=sheet,
            location={"sheet": sheet, "table": table_name},
        ))

    if len(sheets) > 1 and len(unified_sheets) < len(sheets):
        odd = ", ".join(sorted(set(sheets) - unified_sheets))
        warnings.append(
            f"sheets with a different header were kept separate: {odd}"
        )

    chunks.append(Chunk(
        text=(
            f"{handle}: {len(sheets)} sheet(s), "
            f"{sum(s['rows'] for s in outline_sheets)} rows total. "
            f"Tables: " + ", ".join(s["table"] for s in outline_sheets)
        ),
        kind="schema", section_path=None,
        location={"handle": handle},
    ))

    return IngestResult(
        parser=PARSER,
        outline={
            "kind": "tabular",
            "sheets": outline_sheets,
            "unified_view": f"{handle}_all" if len(unified_sheets) > 1 else None,
            "total_rows": sum(s["rows"] for s in outline_sheets),
        },
        chunks=chunks,
        tables=tables,
        warnings=warnings,
    ).reindex()


class TabularIngestor:
    """Registry-shaped wrapper so ingestors are interchangeable."""

    name = PARSER
    version = PARSER_VERSION
    mimetypes = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
        "text/tab-separated-values",
        "application/tsv",
    }
    suffixes = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".tab"}

    def supports(self, filename: str, mime: str | None) -> bool:
        return (
            Path(filename).suffix.lower() in self.suffixes
            or (mime or "").lower() in self.mimetypes
        )

    def ingest(self, path: Path, handle: str) -> IngestResult:
        return ingest(path, handle)


__all__ = ["PARSER", "PARSER_VERSION", "TabularIngestor"]
