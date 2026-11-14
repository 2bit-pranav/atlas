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


def test_sheet_columns_named_by_letter_are_read_as_their_header_names(tmp_path) -> None:
    """read_xlsx shows a grid with letters; the model wrote `SELECT A, SUM(C)`, failed twice and typed
    totals instead (2026-11-14). A query that fails on letters is run again with the header names."""
    from openpyxl import Workbook

    from agent.tools.doc_reading import by_letter, xlsx_rows

    wb = Workbook()
    ws = wb.active
    ws.title = "Jan"
    for row in (["region", "rep", "revenue"], ["North", "r1", 10.5], ["North", "r2", 4.5], ["South", "r3", 7]):
        ws.append(row)
    wb.save(tmp_path / "s.xlsx")
    _, rows, _ = xlsx_rows(tmp_path / "s.xlsx", 'SELECT A, SUM(C) FROM "Jan" GROUP BY A ORDER BY A')
    assert rows == [("North", 15.0), ("South", 7.0)]
    assert by_letter("SELECT A FROM Jan WHERE A = 'B'", {"Jan": ["region", "rep"]}) == \
        "SELECT \"region\" FROM Jan WHERE \"region\" = 'B'"            # a quoted 'B' is a value, kept


def test_a_reference_that_cannot_be_read_is_an_error_not_text(tmp_path) -> None:
    """In table cells and with one closing brace, references went into the document as text (2026-11-14)."""
    import pytest

    from agent.tools.documents.base import DocumentError
    from agent.tools.documents.references import expand

    (tmp_path / "o.csv").write_text("id,amount\n1,2.5\n2,4\n")
    place = lambda n: tmp_path / n  # noqa: E731
    with pytest.raises(DocumentError, match="not a reference"):
        expand("| North | {{o.csv sql: SUM(amount)} |", place)
    assert expand("| Total | {{o.csv sql: SELECT SUM(amount) FROM o.csv}} |", place) == "| Total | 6.5 |"   # one value fits
    with pytest.raises(DocumentError, match="must give one value"):
        expand("| North | {{o.csv sql: SELECT * FROM o}} |", place)
    assert "6.5" in expand("Total:\n{{o.csv sql: SELECT SUM(amount) AS total FROM o}}\n", place)


def test_a_table_mark_joined_to_its_first_row_keeps_the_row() -> None:
    """The model dropped the mark's `]` and the line break: the header row went with the mark (2026-11-14)."""
    from agent.tools.documents.markdown import without_reader_marks

    out = without_reader_marks("[t1: table, 3 rows x 2 cols. A cell is t1.rROW.cCOL, columns counted from the left: "
                               "c1, c2, ... r1: Name | City\nr2: Asha | Pune\nr3: Liam | Leeds")
    assert out.splitlines() == ["| Name | City |", "|---|---|", "| Asha | Pune |", "| Liam | Leeds |"]


def test_a_table_copied_onto_one_line_is_a_table_again() -> None:
    """The whole table as one line, `r1: ... r2: ... r3: ...` (2026-11-14)."""
    from agent.tools.documents.markdown import without_reader_marks

    want = ["| Name | City |", "|---|---|", "| Asha | Pune |", "| Liam | Leeds |"]
    assert without_reader_marks("[t1: table, 3 rows x 2 cols. A cell ... c1, c2, ... r1: Name | City r2: Asha | Pune "
                                "r3: Liam | Leeds").splitlines() == want
    assert without_reader_marks("r1: Name | City r2: Asha | Pune r3: Liam | Leeds").splitlines() == want


def test_a_sheet_name_used_as_a_value_is_refused_with_the_right_form(tmp_path) -> None:
    """`SELECT "Jan" AS month ... GROUP BY "Jan", region` grouped by whole rows: 40 one-row totals (2026-11-14)."""
    import pytest
    from openpyxl import Workbook

    from agent.tools.doc_reading import QueryError, xlsx_rows

    wb = Workbook()
    ws = wb.active
    ws.title = "Jan"
    for row in (["region", "revenue"], ["North", 1.5], ["North", 2]):
        ws.append(row)
    wb.save(tmp_path / "s.xlsx")
    with pytest.raises(QueryError, match="single quotes"):
        xlsx_rows(tmp_path / "s.xlsx", 'SELECT "Jan" AS month, "region", SUM("revenue") FROM "Jan" GROUP BY "Jan", "region"')
    assert xlsx_rows(tmp_path / "s.xlsx", "SELECT 'Jan' AS month, \"region\", SUM(\"revenue\") FROM \"Jan\" "
                                          'GROUP BY "region"')[1] == [("Jan", "North", 3.5)]
