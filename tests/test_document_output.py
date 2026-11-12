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
