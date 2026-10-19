"""Combine spreadsheets into one workbook.

    python combine_xlsx.py out.xlsx jan.xlsx feb.xlsx            # every sheet, side by side
    python combine_xlsx.py out.xlsx a.xlsx:Sales b.csv            # chosen sheets, and CSVs
    python combine_xlsx.py out.xlsx jan.xlsx feb.xlsx --stack     # rows appended into one sheet

Side by side, each sheet keeps its rows and is named after its file and sheet.
`--stack` writes one sheet: the first header, then every source's rows, with
a `source` column saying where each row came from. It refuses when the headers
differ, rather than lining up columns that do not match.
Values only: formulas arrive as their cached results.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import created, fail, main_wrapper, output_path, require, resolve, unquote  # noqa: E402

openpyxl, = require("openpyxl")

#: `file.xlsx:Sheet name` -- only after an .xlsx/.xlsm, so `C:/x.xlsx` is a file.
_SPEC = re.compile(r"^(?P<file>.+?\.xls[xm]):(?P<sheet>.+)$", re.I)


def sources(arg: str) -> list[tuple[str, list[list]]]:
    """(label, rows) for each sheet an argument names."""
    arg = unquote(arg)
    m = _SPEC.match(arg)
    path = resolve(m["file"] if m else arg)
    if not path.is_file():
        raise FileNotFoundError(2, "no such file", str(path))
    if path.suffix.lower() in (".csv", ".tsv"):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [(path.stem, [list(r) for r in csv.reader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")])]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    names = [m["sheet"]] if m else wb.sheetnames
    missing = [n for n in names if n not in wb.sheetnames]
    if missing:
        raise ValueError(f"{path.name} has no sheet {missing[0]!r}; it has {', '.join(wb.sheetnames)}")
    out = [(path.stem if len(wb.sheetnames) == 1 else f"{path.stem} {n}",
            [list(r) for r in wb[n].iter_rows(values_only=True)]) for n in names]
    wb.close()
    return out


def _title(label: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "_", label)[:31] or "Sheet"
    title, n = base, 2
    while title.lower() in used:
        title = f"{base[:28]}_{n}"
        n += 1
    used.add(title.lower())
    return title


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="the .xlsx to write")
    parser.add_argument("inputs", nargs="+", help="file.xlsx, file.xlsx:Sheet, or file.csv")
    parser.add_argument("--stack", action="store_true", help="append all rows into one sheet")
    args = parser.parse_args()

    out = output_path(args.output)
    if out.suffix.lower() != ".xlsx":
        return fail(f"the output must be a .xlsx, not {out.name}")
    try:
        sheets = [s for arg in args.inputs for s in sources(arg)]
    except ValueError as exc:
        return fail(str(exc))
    if not sheets:
        return fail("nothing to combine")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if args.stack:
        header = sheets[0][1][0] if sheets[0][1] else []
        for label, rows in sheets[1:]:
            if rows and [str(c).strip().lower() for c in rows[0]] != [str(c).strip().lower() for c in header]:
                return fail(f"{label} has different columns from {sheets[0][0]}",
                            hint="combine without --stack, or pick sheets with the same header")
        ws = wb.create_sheet("Combined")
        ws.append(["source", *header])
        for label, rows in sheets:
            for row in rows[1:]:
                ws.append([label, *row])
        detail = {"sheets": 1, "rows": ws.max_row - 1, "from": len(sheets)}
    else:
        used: set[str] = set()
        for label, rows in sheets:
            ws = wb.create_sheet(_title(label, used))
            for row in rows:
                ws.append(row)
        detail = {"sheets": len(sheets), "names": ", ".join(wb.sheetnames)}
    wb.save(out)
    print(created(out, **detail))
    return 0


if __name__ == "__main__":
    sys.exit(main_wrapper(main))
