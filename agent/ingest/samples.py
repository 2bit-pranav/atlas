"""Generate the sample corpus (spec L4 done-when: "about ten sample files").

Run:  python -m agent.ingest.samples

Includes the spec's worked example, sales.xlsx with 12 monthly sheets, so the
tool-layer test in section 13 has a real fixture. Also includes the awkward
cases on purpose: a sheet with mismatched headers, non-numeric values in a
numeric column, and a UTF-8 BOM CSV.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Widget", "Gadget", "Doohickey", "Thingamajig"]


def _sales_sheets() -> dict[str, list[dict]]:
    """12 monthly sheets, 104 rows each = 1,248 (the spec's number)."""
    rng = random.Random(7)
    sheets: dict[str, list[dict]] = {}
    for month in MONTHS:
        rows = []
        for i in range(104):
            rows.append({
                "date": f"2026-{MONTHS.index(month) + 1:02d}-{i % 28 + 1:02d}",
                "region": REGIONS[i % 4],
                "product": PRODUCTS[i % 4],
                "units": rng.randint(1, 40),
                "unit_price": round(rng.uniform(5.0, 250.0), 2),
                "revenue": round(rng.uniform(100.0, 9000.0), 2),
            })
        sheets[month] = rows
    # Dirty data on purpose, so the quality-warning path has something real to
    # find. Note the values are "TBD"/"pending" rather than "n/a": pandas
    # silently converts "n/a" to NULL when reading, which is correct but means
    # it would never reach the warning that is supposed to report it.
    sheets["Mar"][5]["revenue"] = "TBD"
    sheets["Mar"][11]["revenue"] = "pending"
    return sheets


def _write_xlsx(path: Path, sheets: dict[str, list[dict]], extra: dict | None = None) -> None:
    import pandas as pd

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False)
        for name, rows in (extra or {}).items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False)


CONTRACT = """Master Services Agreement

This Agreement is made between Acme Corp ("Client") and Globex ("Provider").

1. Term. This Agreement begins on 1 March 2026 and continues for twelve (12)
months unless terminated earlier in accordance with Section 9.

2. Fees. Client shall pay Provider a monthly fee of 4,500 GBP, payable within
thirty (30) days of invoice. Late payments accrue interest at 4% above base.

3. Termination. Either party may terminate this Agreement with ninety (90)
days written notice. Termination does not relieve Client of fees accrued.

4. Termination for cause. Either party may terminate immediately upon material
breach that remains uncured thirty (30) days after written notice.

5. Confidentiality. Each party shall keep the other's Confidential Information
secret for a period of five (5) years following termination.

6. Data protection. Processor shall process Personal Data only on documented
instructions from Controller, in accordance with UK GDPR.

7. Liability. Neither party excludes liability for death or personal injury
caused by negligence, nor for fraud.

8. Governing law. This Agreement is governed by the laws of England and Wales.
"""

NOTES_MD = """# Project notes

## Status

The ingestion worker is single-threaded on purpose. Docling is memory hungry and
we only ever parse one document at a time.

## Open questions

- Should a failed parse block the whole upload, or attach with a warning?
- Where do embeddings run if the model is busy with a run?

## Decisions

Keep the store separate from the chat. One file per chat, deleted with it.
"""


def build(out_dir: Path | None = None) -> list[Path]:
    out_dir = Path(out_dir or Path(__file__).resolve().parents[2] / "samples")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def emit(name: str, data: bytes) -> None:
        p = out_dir / name
        p.write_bytes(data)
        written.append(p)

    sales = out_dir / "sales.xlsx"
    _write_xlsx(
        sales,
        _sales_sheets(),
        extra={"Notes": [{"topic": "kickoff", "detail": "went well"}]},
    )
    written.append(sales)

    # A deliberately mismatched sheet, to prove unification is per-signature.
    odd = out_dir / "mixed_headers.xlsx"
    _write_xlsx(odd, {
        "Q1": [{"month": "Jan", "revenue": 10.0}, {"month": "Feb", "revenue": 12.0}],
        "Q1b": [{"month": "Mar", "revenue": 9.5, "extra": "different header"}],
    })
    written.append(odd)

    rows = _sales_sheets()["Jan"]
    csv_path = out_dir / "sales_jan.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    written.append(csv_path)

    emit("contract.txt", CONTRACT.encode("utf-8"))
    emit("notes.md", NOTES_MD.encode("utf-8"))
    emit("config.json", json.dumps(
        {"model": "e2b", "context_size": 32768, "tools": ["query", "outline"]},
        indent=2).encode("utf-8"))
    emit("server.log", "\n".join(
        f"2026-10-{d:02d} 09:{d:02d}:00 INFO slot {d} prompt eval ok"
        for d in range(1, 20)).encode("utf-8"))
    emit("empty.txt", b"")
    emit("ragged.csv", b"a,b,c\n1,2\n3,4,5,6\n")

    return written


def main() -> int:
    paths = build()
    print(f"wrote {len(paths)} sample files:")
    for p in paths:
        print(f"  {p.name:24s} {p.stat().st_size:>8,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
