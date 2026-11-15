"""When a turn is done is decided by code (agent/recovery/done_check.py), from what failed on 2026-11-12."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent.recovery.done_check import DoneCheck
from agent.tools.documents.create import create


def _turn(ws: Path, request: str, **kw) -> DoneCheck:
    ws.mkdir(parents=True, exist_ok=True)
    check = DoneCheck(ws, request, **kw)
    check._before_invocation(SimpleNamespace())
    return check


def _end(check: DoneCheck, last: str) -> str | None:
    event = SimpleNamespace(result=SimpleNamespace(stop_reason="end_turn",
                                                   message={"content": [{"text": last}]}), resume=None)
    check._after_invocation(event)
    return event.resume


def test_a_broken_document_sends_the_model_back(tmp_path) -> None:
    ws = tmp_path / "ws"
    check = _turn(ws, "Filter orders.csv to the North rows and save them as north.xlsx")
    (ws / "north.xlsx").write_text("id,region,total\n1,North,10\n")          # a script's CSV text, named .xlsx
    resume = _end(check, "Done: north.xlsx has the North rows.")
    assert resume and "north.xlsx does not open" in resume and "create_document" in resume
    assert _end(check, "Done.") is None                                       # once per turn


def test_the_file_asked_for_must_exist(tmp_path) -> None:
    ws = tmp_path / "ws"
    check = _turn(ws, "Make handbook_v2.docx from this document, with Expenses first.")
    assert "handbook_v2.docx" in _end(check, "I have reorganised the handbook.")
    check = _turn(ws, "Make handbook_v2.docx from this document.")
    create(ws / "handbook_v2.docx", "# Handbook")
    assert _end(check, "handbook_v2.docx is ready.") is None


def test_a_file_saved_into_an_allowed_folder_counts(tmp_path) -> None:
    folder = tmp_path / "Reports"
    folder.mkdir()
    check = _turn(tmp_path / "ws", "Save the summary as q3.docx in Reports", place=lambda n: folder / n)
    create(folder / "q3.docx", "# Q3")
    assert _end(check, "Saved q3.docx in Reports.") is None


def test_announcing_the_next_step_and_stopping_is_not_done(tmp_path) -> None:
    check = _turn(tmp_path / "ws", "Put the 12 invoices into one spreadsheet")
    assert "said what you would do next" in _end(check, "I have read all 12 invoices. Now I will create the spreadsheet.")


def test_a_summary_must_have_read_the_document(tmp_path) -> None:
    check = _turn(tmp_path / "ws", "Write a one-page summary of review.pdf")
    check._after_tool(SimpleNamespace(tool_use={"name": "read_pdf"}, result={"content": [{"text":
        "review.pdf: page 1 of 16. The other 15 pages are NOT shown\n\n--- page 1 of 16 ---\nIntro"}]}))
    resume = _end(check, "Here is the summary: the report is about water quality.")
    assert resume and "read 1 of 16 pages of review.pdf" in resume and 'pages="2-16"' in resume


def test_ordinary_answers_are_left_alone(tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws).mkdir()
    (ws / "notes.txt").write_text("x")
    for request, last in (
            ("what does notes.txt say?", "It says x. Let me know if you need anything else."),
            ("What is the capital of France?", "Paris. I'll be happy to help with more."),
            ("summarise this page", "The page is about trains."),                     # no PDF read: nothing to count
            ("is report.pdf in my folder?", "No, there is no report.pdf."),            # named, not asked to be made
    ):
        assert _end(_turn(ws, request), last) is None, request


def test_a_resume_already_set_or_a_turn_that_did_not_end_is_left_alone(tmp_path) -> None:
    check = _turn(tmp_path / "ws", "Make out.docx")
    event = SimpleNamespace(result=SimpleNamespace(stop_reason="end_turn", message={"content": []}), resume="other")
    check._after_invocation(event)
    assert event.resume == "other"
    event = SimpleNamespace(result=SimpleNamespace(stop_reason="max_tokens", message={"content": []}), resume=None)
    check._after_invocation(event)
    assert event.resume is None


def test_a_broken_file_is_marked_on_its_chip(tmp_path) -> None:
    from server.services.workspace import _changed, _scan

    before = _scan(tmp_path)
    (tmp_path / "north.xlsx").write_text("id,region\n")
    create(tmp_path / "ok.docx", "# fine")
    files = {f["name"]: f for f in _changed(before, _scan(tmp_path), tmp_path)}
    assert "broken" in files["north.xlsx"] and "broken" not in files["ok.docx"]
