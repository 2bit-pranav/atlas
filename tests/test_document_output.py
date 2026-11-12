"""What create_document makes of what a small model writes (agent/tools/documents/)."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from agent.tools.documents.create import create
from agent.tools.documents.markdown import without_reader_marks

HERE = Path(__file__).parent


def test_reader_marks_copied_into_a_new_document_are_taken_out(tmp_path) -> None:
    """The model's own content from the evaluation (2026-11-12): marks as text, the table lost."""
    content = (HERE / "fixtures" / "copied_reader_output.md").read_text(encoding="utf-8")
    create(tmp_path / "handbook_v2.docx", content)
    doc = Document(str(tmp_path / "handbook_v2.docx"))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "[b" not in text and "[t1" not in text and "r1:" not in text
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["Name", "Role", "City", "Joined"]
    assert [c.text for c in table.rows[1].cells] == ["Asha Verma", "Engineer", "Pune", "2019"]
    assert len(table.rows) == 16


def test_ordinary_markdown_is_left_alone() -> None:
    text = "# Plan [draft]\n\nSee [b2 notes](x) and r2: not a row.\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    assert without_reader_marks(text) == text


def test_a_csv_can_be_queried_and_sql_reads_no_other_file(tmp_path) -> None:
    import openpyxl

    from agent.tools.doc_reading import _query, query_csv

    (tmp_path / "secret.txt").write_text("TOP-SECRET-VALUE")
    rows = ["id,region,total"] + [f"{i},{'North' if i % 2 else 'South'},{i * 10.5}" for i in range(1, 61)]
    (tmp_path / "orders.csv").write_text("\n".join(rows), encoding="utf-8")
    out = query_csv(tmp_path / "orders.csv", "SELECT region, ROUND(SUM(total), 2) AS t FROM orders GROUP BY region ORDER BY region")
    assert "North | 9450" in out and "South | 9765" in out
    assert "1 row" in query_csv(tmp_path / "orders.csv", "SELECT COUNT(*) FROM data")
    # A SELECT could call DuckDB's own readers and read any file, past every path check (2026-11-12).
    secret = (tmp_path / "secret.txt").as_posix()
    for sql in (f"SELECT * FROM read_text('{secret}')", f"SELECT * FROM read_csv_auto('{secret}')",
                f"SELECT * FROM glob('{tmp_path.as_posix()}/*')"):
        assert "TOP-SECRET" not in str(query_csv(tmp_path / "orders.csv", sql)), sql
    book = openpyxl.Workbook()
    book.active.title = "S"
    book.active.append(["a"])
    book.active.append([1])
    book.save(tmp_path / "x.xlsx")
    assert "TOP-SECRET" not in str(_query(tmp_path / "x.xlsx", f"SELECT content FROM read_text('{secret}')", ["x.xlsx"]))
    assert "error" in str(query_csv(tmp_path / "orders.csv", "DELETE FROM data")).lower()
