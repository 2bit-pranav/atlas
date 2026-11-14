"""Writing tools (agent/tools/documents/tool.py, blocks.py) and their registration
with a skill (agent/runtime/skill_tools.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import text_of

from agent.ingest.store import Store
from agent.runtime.skill_tools import SkillTools
from agent.tools.doc_reading import doc_read_tools
from agent.tools.documents.tool import document_tools


def _docx(path: Path) -> Path:
    from docx import Document

    d = Document()
    d.add_heading("Supplier review", 1)
    d.add_paragraph("Keep Northwind as the main supplier.")
    t = d.add_table(rows=3, cols=3)
    for r, row in enumerate([("Supplier", "Unit price", "Lead time"), ("Northwind", "12.40", "14 days"),
                             ("Brightline", "9.85", "23 days")]):
        for c, value in enumerate(row):
            t.rows[r].cells[c].text = value
    d.save(str(path))
    return path


def _xlsx(path: Path) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    for name, values in (("Jan", (1200, 3400.5)), ("Mar", (4100.5, 2950.25))):
        ws = wb.create_sheet(name)
        ws.append(["region", "revenue"])
        for region, v in zip(("North", "South"), values, strict=True):
            ws.append([region, v])
    wb.remove(wb["Sheet"])
    wb.save(str(path))
    return path


@pytest.fixture
def env(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    store = Store(tmp_path / "parsed")
    tools = document_tools(ws, lambda p: p.name, lambda p: ws / p, store, "c1")
    return SimpleNamespace(ws=ws, store=store, **tools)


def _owned(env, path: Path) -> None:
    sha = env.store.submit(path, "c1")
    assert sha and env.store.wait(sha, lambda e: e["status"] == "ready", 30)


def test_edit_docx_changes_one_cell_and_nothing_else(env) -> None:
    from docx import Document

    path = _docx(env.ws / "s.docx")
    _owned(env, path)
    out = env.edit_docx(path="s.docx", block="t1.r3.c3", text="18 days")
    assert '"23 days" is now "18 days"' in out
    d = Document(str(path))
    assert [c.text for c in d.tables[0].rows[2].cells] == ["Brightline", "9.85", "18 days"]
    assert d.tables[0].rows[1].cells[2].text == "14 days"
    assert d.paragraphs[1].text == "Keep Northwind as the main supplier."


def test_edit_docx_paragraph_keeps_its_style(env) -> None:
    from docx import Document

    path = _docx(env.ws / "s.docx")
    _owned(env, path)
    env.edit_docx(path="s.docx", block="b1", text="Supplier review 2026")
    p = Document(str(path)).paragraphs[0]
    assert p.text == "Supplier review 2026" and p.style.name == "Heading 1"


def test_reader_ids_are_the_edit_addresses(env) -> None:
    """What read_docx prints for a cell is what edit_docx takes."""
    _docx(env.ws / "s.docx")
    _, read_docx, _ = doc_read_tools(env.store, "c1", lambda p: env.ws / p, env.ws)
    out = read_docx(path="s.docx")
    assert "r3: Brightline | 9.85 | 23 days" in out and "t1.rROW.cCOL" in out
    env.edit_docx(path="s.docx", block="t1.r3.c3", text="18 days")
    assert "r3: Brightline | 9.85 | 18 days" in read_docx(path="s.docx")   # re-ingested after the edit


def test_bad_addresses_say_what_exists(env) -> None:
    path = _docx(env.ws / "s.docx")
    _owned(env, path)
    assert "rows are r1-r3" in text_of(env.edit_docx(path="s.docx", block="t1.r9.c1", text="x"))
    assert "paragraphs are b1-b" in text_of(env.edit_docx(path="s.docx", block="b99", text="x"))
    assert "not a block id" in text_of(env.edit_docx(path="s.docx", block="| Brightline | 9.85 |", text="x"))


def test_an_unread_or_changed_file_is_not_edited_by_address(env) -> None:
    path = _docx(env.ws / "s.docx")
    assert "Read it first" in text_of(env.edit_docx(path="s.docx", block="b1", text="x"))   # never read here
    _owned(env, path)
    from docx import Document

    d = Document(str(path))
    d.add_paragraph("added elsewhere")
    d.save(str(path))                                                                    # changed since
    assert "Read it first" in text_of(env.edit_docx(path="s.docx", block="b1", text="x"))


def test_set_cell_sets_a_number_and_keeps_the_rest(env) -> None:
    from openpyxl import load_workbook

    path = _xlsx(env.ws / "sales.xlsx")
    _owned(env, path)
    out = env.set_cell(path="sales.xlsx", cell="Mar!B2", value="5000")
    assert "4100.5 is now '5000'" in out
    wb = load_workbook(str(path))
    assert wb["Mar"]["B2"].value == 5000 and wb["Mar"]["B3"].value == 2950.25
    assert wb["Jan"]["B2"].value == 1200 and wb["Jan"]["B3"].value == 3400.5
    assert "Sheets: Jan, Mar" in text_of(env.set_cell(path="sales.xlsx", cell="Apr!B2", value="1"))
    assert "not a cell" in text_of(env.set_cell(path="sales.xlsx", cell="North", value="1"))


def test_create_document_never_replaces_a_file(env) -> None:
    from openpyxl import load_workbook

    path = _xlsx(env.ws / "sales.xlsx")
    before = path.read_bytes()
    out = env.create_document(path="sales.xlsx", content="## Mar\n| region | revenue |\n|---|---|\n| North | 1 |")
    assert "left unchanged, so this is saved as sales-2.xlsx" in out
    assert path.read_bytes() == before
    assert load_workbook(str(env.ws / "sales-2.xlsx"))["Mar"]["B2"].value == 1


def _agent(tools: dict, active: list[str]):
    from strands.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.process_tools([t for name, t in tools.items() if name == "read_text"])
    state = {"agent_skills": {"activated_skills": active}}
    return SimpleNamespace(tool_registry=registry, state=SimpleNamespace(get=state.get))


def test_a_skill_brings_its_tools_in_one_fixed_order(env) -> None:
    from agent.tools.reading import read_tools

    text, _ = read_tools(lambda p: env.ws / p, lambda p: p.name, False)
    writers = {"create_document": env.create_document, "edit_docx": env.edit_docx, "set_cell": env.set_cell}
    hook = SkillTools(writers)
    a = _agent({"read_text": text}, [])
    hook.sync(a)
    assert list(a.tool_registry.registry) == ["read_text"]                    # nothing loaded: read only
    a = _agent({"read_text": text}, ["xlsx", "docx"])
    hook.sync(a)
    b = _agent({"read_text": text}, ["docx", "xlsx"])
    hook.sync(b)
    order = ["read_text", "create_document", "edit_docx", "set_cell"]
    assert list(a.tool_registry.registry) == list(b.tool_registry.registry) == order
    hook.sync(b)                                                              # idempotent
    assert list(b.tool_registry.registry) == order
    off = SkillTools({k: v for k, v in writers.items() if k != "set_cell"})   # switched off in settings
    c = _agent({"read_text": text}, ["xlsx"])
    off.sync(c)
    assert list(c.tool_registry.registry) == ["read_text", "create_document"]


def test_a_message_naming_a_document_starts_with_its_tools(env) -> None:
    """The model tried `write` on a .docx before create_document in 8 of 19 writing runs (2026-11-12)."""
    from agent.runtime.skill_tools import for_message
    from agent.tools.reading import read_tools

    assert for_message("Put the 12 invoices into one spreadsheet", ["inv01.pdf"]) == {"xlsx", "pdf"}
    assert for_message("Make handbook_v2.docx from this", []) == {"docx"}
    assert for_message("summarise this in a Word document", []) == {"docx"}
    assert for_message("what is the capital of France?", ["notes.txt"]) == set()
    assert for_message("filter orders", ["orders.csv"]) == {"xlsx"}

    text, _ = read_tools(lambda p: env.ws / p, lambda p: p.name, False)
    writers = {"create_document": env.create_document, "edit_docx": env.edit_docx, "set_cell": env.set_cell}
    hook = SkillTools(writers, preload={"xlsx"})
    a = _agent({"read_text": text}, [])
    hook.sync(a)
    assert list(a.tool_registry.registry) == ["read_text", "create_document", "set_cell"]
    a.state = SimpleNamespace(get={"agent_skills": {"activated_skills": ["docx"]}}.get)   # loading a skill keeps them
    hook.sync(a)
    assert list(a.tool_registry.registry) == ["read_text", "create_document", "edit_docx", "set_cell"]


def test_a_refused_write_on_a_document_brings_the_tool_it_names(env) -> None:
    from agent.tools.reading import read_tools

    text, _ = read_tools(lambda p: env.ws / p, lambda p: p.name, False)
    hook = SkillTools({"create_document": env.create_document, "edit_docx": env.edit_docx})
    a = _agent({"read_text": text}, [])
    hook._after_tool(SimpleNamespace(tool_use={"name": "write", "input": {"path": "report.docx"}}, agent=a, result={}))
    assert list(a.tool_registry.registry) == ["read_text", "create_document", "edit_docx"]
    hook._after_tool(SimpleNamespace(tool_use={"name": "write", "input": {"path": "notes.txt"}}, agent=a, result={}))
    assert list(a.tool_registry.registry) == ["read_text", "create_document", "edit_docx"]


def test_a_draft_made_this_turn_may_be_made_again_but_never_a_file_from_before(tmp_path) -> None:
    """Sent back by the done check, the model's full summary went to summary-2.docx beside its own
    one-bullet summary.docx (2026-11-14): the turn's own draft is replaced; an older file never is."""
    from agent.tools.documents.tool import _free

    old, draft = tmp_path / "old.docx", tmp_path / "summary.docx"
    old.write_text("x")
    draft.write_text("x")
    drafts = {draft}
    assert _free(draft, drafts) == draft
    assert _free(old, drafts) == tmp_path / "old-2.docx"
    assert _free(draft) == tmp_path / "summary-2.docx"          # no drafts known: never replaced
