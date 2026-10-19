"""Export spreadsheet sheets as CSV files.

    python xlsx_to_csv.py sales.xlsx                 # the first sheet -> sales.csv
    python xlsx_to_csv.py sales.xlsx --sheet Mar     # one named sheet -> sales_Mar.csv
    python xlsx_to_csv.py sales.xlsx --all-sheets    # every sheet, one file each

Cached values are written, never formula strings. UTF-8 with a BOM, so Excel
opens non-English text correctly.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--sheet", default="", help="export only this sheet")
    parser.add_argument("--all-sheets", action="store_true", help="one CSV per sheet")
    args = parser.parse_args()

    path = resolve(args.file)
    if not path.is_file():
        return fail(f"no such file: {path}")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = unquote(args.sheet)
    if sheet and sheet not in wb.sheetnames:
        return fail(f"no sheet {sheet!r}", hint=f"sheets: {', '.join(wb.sheetnames)}")
    names = wb.sheetnames if args.all_sheets else [sheet or wb.sheetnames[0]]
    written = []
    for name in names:
        suffix = "" if len(names) == 1 and not sheet else "_" + re.sub(r"[^\w.-]+", "_", name)
        out = output_path(f"{path.stem}{suffix}.csv")
        rows = 0
        with out.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            for row in wb[name].iter_rows(values_only=True):
                writer.writerow(["" if v is None else v for v in row])
                rows += 1
        written.append(f"{out.name} ({rows} rows)")
    wb.close()
    print(created(", ".join(written)))
    return 0


if __name__ == "__main__":
    sys.exit(main_wrapper(main))
