"""Inspect a spreadsheet: sheets, headers, shapes, and a few sample rows.

The first thing to know about any workbook is *its shape*. A 13-sheet workbook
where one sheet holds 40,000 rows and the rest hold 12 needs completely
different treatment, and guessing produces wrong sums with total confidence.

So `--shape` is the default: it is cheap, it is always the right first call,
and it tells the model which sheet to query and how big it is.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import (  # noqa: E402
    add_common_arguments,
    fail,
    header,
    limit_for,
    main_wrapper,
    require,
    resolve,
    truncate,
)

openpyxl, = require("openpyxl")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a spreadsheet")
    parser.add_argument("path")
    parser.add_argument("--sheet", default="", help="inspect only this sheet")
    parser.add_argument("--rows", type=int, default=5, help="sample rows to show")
    parser.add_argument("--all-sheets", action="store_true",
                        help="sample every sheet, not just the first")
    parser.add_argument("--formulas", action="store_true",
                        help="show formulas instead of cached values")
    add_common_arguments(parser)
    args = parser.parse_args()

    path = resolve(args.path)
    if not path.is_file():
        return fail(f"no such file: {path}")
    if path.suffix.lower() not in (".xlsx", ".xlsm", ".xltx"):
        return fail(f"{path.name} is not a modern Excel file",
                    hint=".xls is not supported; ask the user to save as .xlsx")

    # read_only + data_only: formulas are returned as their cached values, so a
    # SUM cell reads as a number instead of the string "=SUM(B2:B40)".
    #
    # The two views need TWO loads and cannot be combined. data_only=True
    # yields the cached value with the formula gone; the default yields the
    # formula string with no value. A file openpyxl wrote itself has no cached
    # values at all, so data_only reads back None everywhere -- which looks
    # exactly like an empty column.
    book = openpyxl.load_workbook(str(path), read_only=True,
                                  data_only=not args.formulas)
    if args.formulas:
        print("note: showing formula strings; cached results are not available "
              "from this view.")
    limit, hint = limit_for(args)

    names = book.sheetnames
    print(header(file=path.name, sheets=len(names), names=", ".join(names)))
    print()

    targets = [args.sheet] if args.sheet else (
        names if args.all_sheets else [names[0]]
    )
    if args.sheet and args.sheet not in names:
        return fail(f"no sheet named {args.sheet!r}",
                    hint=f"sheets are: {', '.join(names)}")

    for name in targets:
        sheet = book[name]
        rows = sheet.iter_rows(values_only=True)
        header_row = next(rows, None)
        samples = []
        for _, row in zip(range(args.rows), rows):
            samples.append([("" if v is None else v) for v in row])
        width = len(header_row) if header_row else 0
        print(f"--- sheet {name!r}: {sheet.max_row} rows x {width} cols ---")
        if header_row is not None:
            print("columns: " + ", ".join(
                str(c) if c is not None else "(unnamed)" for c in header_row))
        for row in samples:
            print("  " + " | ".join(str(v)[:28] for v in row))
        if sheet.max_row > args.rows + (1 if header_row else 0):
            print(f"  [{sheet.max_row} rows total; showing {args.rows}; "
                  f"use query_xlsx.py to aggregate]")
        print()

    if len(targets) == 1 and not args.all_sheets and len(names) > 1:
        text = " | ".join(names)
        body, cut = truncate(f"other sheets: {text}", limit, more_hint=hint)
        print(body)
    book.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))