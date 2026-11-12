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


def _sources(tmp_path: Path) -> None:
    import openpyxl
    from docx import Document as NewDocument

    doc = NewDocument()
    doc.add_paragraph("Intro")
    t = doc.add_table(rows=3, cols=2)
    for r, row in enumerate([["Name", "City"], ["Asha | V", "Pune"], ["Liam", "Leeds"]]):
        for c, value in enumerate(row):
            t.cell(r, c).text = value
    doc.save(str(tmp_path / "staff.docx"))
    book = openpyxl.Workbook()
    north = book.active
    north.title = "North"
    north.append(["Item", "Total"])
    for i in range(1, 41):
        north.append([f"item{i}", i * 181.511])
    book.create_sheet("South").append(["Item", "Total"])
    book.save(tmp_path / "sales.xlsx")
    (tmp_path / "orders.csv").write_text("region,total\nNorth,10.5\nNorth,4.25\nSouth,7\n", encoding="utf-8")


def test_references_copy_data_in_exactly(tmp_path) -> None:
    from agent.tools.documents.references import expand, referenced

    _sources(tmp_path)
    content = ("# Report\n\n{{staff.docx#t1}}\n\n## North\n\n{{sales.xlsx!North!A1:B4}}\n\n"
               "## Total\n\n{{sales.xlsx sql: SELECT ROUND(SUM(Total), 2) AS total FROM North}}\n\n"
               "## By region\n\n{{ orders.csv sql: SELECT region, SUM(total) AS t FROM orders GROUP BY region ORDER BY region }}")
    assert referenced(content) == ["staff.docx", "sales.xlsx", "sales.xlsx", "orders.csv"]
    out = expand(content, lambda name: tmp_path / name)
    assert "| Name | City |" in out and r"| Asha \| V | Pune |" in out
    assert "| item3 | 544.533 |" in out
    assert "| total |" in out and "| 148839.02 |" in out   # 181.511 x (1 + ... + 40) = 181.511 x 820, by code
    assert "| North | 14.75 |" in out and "| South | 7 |" in out
    create(tmp_path / "report.xlsx", out)
    import openpyxl

    sheets = openpyxl.load_workbook(tmp_path / "report.xlsx").sheetnames
    assert "North" in sheets and "Total" in sheets


def test_a_bad_reference_names_itself(tmp_path) -> None:
    import pytest

    from agent.tools.documents.base import DocumentError
    from agent.tools.documents.references import expand

    _sources(tmp_path)
    for ref, words in (("{{staff.docx#t4}}", "1 table(s); there is no t4"), ("{{missing.xlsx!A1:B2}}", "no file"),
                       ("{{sales.xlsx!East!A1:B2}}", "no sheet 'East'"), ("{{sales.xlsx!A1}}", "not a range"),
                       ("{{orders.csv sql: SELECT nope FROM orders}}", "the query failed"),
                       ("{{orders.csv sql: DELETE FROM orders}}", "only one SELECT")):
        with pytest.raises(DocumentError, match=words.replace("(", r"\(").replace(")", r"\)")):
            expand(f"x\n\n{ref}\n", lambda name: tmp_path / name)


def test_a_reference_is_checked_like_a_read(tmp_path) -> None:
    import asyncio
    from types import SimpleNamespace

    from helpers import Asked

    from agent.safety.policy import ToolPolicy
    from agent.safety.protected import Protected
    from agent.safety.scope import Scope

    data, ws, outside = tmp_path / ".data", tmp_path / ".data" / "chats" / "c1", tmp_path / "private"
    ws.mkdir(parents=True)
    outside.mkdir()
    (data / "pairing-token").write_text("TOK")
    asked = Asked("denied")
    policy = ToolPolicy(Scope(ws, protected=Protected(root=tmp_path / "atlas", data=data,
                                                      mcp_config=tmp_path / "mcp.json", workspace=ws)), approver=asked)

    def call(content: str) -> object:
        event = SimpleNamespace(tool_use={"name": "create_document", "toolUseId": "t",
                                          "input": {"path": "out.docx", "content": content}},
                                selected_tool=SimpleNamespace(tool_name="create_document"), cancel_tool=False)
        asyncio.run(policy._before(event))
        return event.cancel_tool

    assert "Atlas's own data" in str(call("{{../../pairing-token.csv sql: SELECT 1}}"))
    assert call(f"{{{{{outside.as_posix()}/bank.csv sql: SELECT 1}}}}") and asked.calls   # outside the folders asks
