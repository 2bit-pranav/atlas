"""The harder document tasks' graders (tests/live/harder.py), offline.

A right answer is made the way the model should make it: create_document, with
references copying the data in. Each wrong one is a failure the evaluation saw
(2026-11-12). Each grader must pass the first and fail the others.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "live"))
import harder  # noqa: E402
import suite  # noqa: E402

from agent.tools.documents.create import create  # noqa: E402
from agent.tools.documents.references import expand  # noqa: E402


@pytest.fixture(scope="module")
def inputs(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("inputs")
    harder.build(folder)
    return folder


def _run(tmp_path: Path, inputs: Path, uploads: tuple[str, ...], answer: str = ""):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    for name in uploads:
        shutil.copy(inputs / name, ws / name)
    return suite.Run("t", False, "c", {"render": [{"kind": "text", "text": answer}]}, ws, [], tmp_path)


def _all(facts: dict[str, bool]) -> bool:
    return all(facts.values())


def _make(run, name: str, markdown: str) -> None:
    create(run.workspace / name, expand(markdown, lambda n: run.workspace / n))


def test_the_inputs_hold_what_the_graders_expect(inputs) -> None:
    from agent.tools.doc_reading import csv_rows, xlsx_rows

    header, rows, _ = xlsx_rows(inputs / "sales_q1.xlsx", 'SELECT ROUND(SUM(revenue), 2) FROM "Jan" WHERE region = \'North\'')
    assert rows[0][0] == harder.DATA["totals"]["Jan/North"]
    header, rows = csv_rows(inputs / "orders.csv", "SELECT ROUND(SUM(amount), 2) FROM orders WHERE region = 'North'")
    assert rows[0][0] == harder.DATA["north_total"]
    assert (inputs / "orders.csv").read_bytes() == harder.orders_csv()


def test_invoices(tmp_path, inputs) -> None:
    run = _run(tmp_path, inputs, (), f"The total is {harder.DATA['invoice_total']:,.2f}.")
    table = "\n".join(f"| {no} | {v} | {d} | {a:.2f} |" for no, v, d, a in harder.DATA["invoices"])
    _make(run, "invoices.xlsx", "# Invoices\n\n| Number | Vendor | Date | Amount |\n|---|---|---|---|\n" + table)
    assert _all(harder.g_invoices(run))
    rows = harder.DATA["invoices"]
    shuffled = "\n".join(f"| {no} | {v} | {d} | {b[3]:.2f} |" for (no, v, d, _), b in zip(rows, rows[1:] + rows[:1], strict=True))
    (run.workspace / "invoices.xlsx").unlink()
    _make(run, "invoices.xlsx", "# Invoices\n\n| Number | Vendor | Date | Amount |\n|---|---|---|---|\n" + shuffled)
    assert not _all(harder.g_invoices(run))                      # amounts on the wrong rows
    (run.workspace / "invoices.xlsx").unlink()
    assert harder.g_invoices(run) == {"invoices.xlsx opens as a workbook": False}   # never made


def test_summary(tmp_path, inputs) -> None:
    run = _run(tmp_path, inputs, ("review.pdf",))
    bullets = "\n".join(f"- {title}: {fact}." for title, fact, _ in harder.SECTIONS)
    _make(run, "summary.docx", "# Corvane River review 2026\n\n" + bullets)
    assert _all(harder.g_review(run))
    (run.workspace / "summary.docx").unlink()
    _make(run, "summary.docx", "# Summary\n\n- Water quality: nitrate fell to 4.2 mg/L.")   # page 1 only
    facts = harder.g_review(run)
    assert facts["Water quality: 4.2"] and not facts["Budget: 48900"]


def test_sales(tmp_path, inputs) -> None:
    run = _run(tmp_path, inputs, ("sales_q1.xlsx",))
    queries = "\n\n".join(f"## {m}\n\n{{{{sales_q1.xlsx sql: SELECT region, ROUND(SUM(revenue), 2) AS total FROM \"{m}\" "
                          f"GROUP BY region ORDER BY region}}}}" for m in harder.MONTHS)
    _make(run, "q1_report.docx", "# Q1 revenue by region\n\n" + queries)
    facts = harder.g_sales(run)
    assert _all(facts), [k for k, v in facts.items() if not v]
    (run.workspace / "q1_report.docx").unlink()
    _make(run, "q1_report.docx", "# Q1\n\n| Region | Jan |\n|---|---|\n| North | 6776.70 |")   # typed, wrong
    assert not _all(harder.g_sales(run))


def test_handbook(tmp_path, inputs) -> None:
    run = _run(tmp_path, inputs, ("handbook.docx",))
    _make(run, "handbook_v2.docx", "# Staff handbook\n\n## Directory\n\n{{handbook.docx#t1}}\n\n## Expenses\n\n"
                                   "Claims above 300 euros need a manager's sign-off.\n\n## Leave policy\n\n"
                                   "Every employee gets 24 days of paid leave.")
    facts = harder.g_handbook(run)
    assert _all(facts), [k for k, v in facts.items() if not v]
    # The evaluation's failure: the reader's output written as the document. create_document now
    # repairs that, so it is written past it here, as python-docx would have.
    from docx import Document

    bad = Document()
    bad.add_paragraph("[b2] Intro")
    bad.add_paragraph("[t1: table, 16 rows x 4 cols]")
    bad.add_paragraph("r1: Name | Role | City | Joined")
    bad.save(str(run.workspace / "handbook_v2.docx"))
    facts = harder.g_handbook(run)
    assert not facts["no reader marks"] and not facts["the Directory is one real table"]


def test_orders(tmp_path, inputs) -> None:
    run = _run(tmp_path, inputs, ("orders.csv",))
    _make(run, "north.xlsx", "# North\n\n{{orders.csv sql: SELECT * FROM orders WHERE region = 'North' ORDER BY order_id}}"
                             "\n\n# Total\n\n{{orders.csv sql: SELECT ROUND(SUM(amount), 2) AS total FROM orders WHERE region = 'North'}}")
    facts = harder.g_orders(run)
    assert facts["all North orders"] and facts["no other region's orders"] and facts["orders.csv left unchanged"]
    # The evaluation's failure: CSV text saved as north.xlsx, the upload overwritten.
    (run.workspace / "north.xlsx").write_text("order_id,region\nO1000,North\n")
    (run.workspace / "orders.csv").write_text("order_id,region\nO1000,North\n")
    assert harder.g_orders(run) == {"orders.csv left unchanged": False, "north.xlsx opens as a workbook": False}


def test_the_hard_tasks_are_in_the_suite() -> None:
    hard = [t for t in suite.TASKS if "hard" in t.tags]
    assert [t.name for t in hard] == ["hard-invoices", "hard-summary", "hard-sales", "hard-handbook", "hard-orders"]
    assert all(t.uploads for t in hard)
