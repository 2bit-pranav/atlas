"""run_skill (agent/tools/skills_run.py): a skill's script as a typed call, no shell (plan 3.6)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from agent.tools.skills_run import path_args, run, skill_effects, skill_run_tools

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def _pdf(path: Path, pages: int) -> None:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 200)
    doc.save(str(path))


@pytest.fixture
def run_skill(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tool,) = skill_run_tools(SKILLS, lambda: {"pdf", "xlsx"}, ws, lambda p: ws / p, lambda: False)
    return ws, tool


def test_a_script_runs_and_never_replaces_a_file(run_skill) -> None:
    ws, tool = run_skill
    _pdf(ws / "a.pdf", 2)
    _pdf(ws / "b.pdf", 3)
    assert "combined.pdf" in str(tool(skill="pdf", script="merge_pdf.py", args=["combined.pdf", "a.pdf", "b.pdf:1-2"]))
    before = (ws / "a.pdf").read_bytes()
    out = str(tool(skill="pdf", script="merge_pdf.py", args=["a.pdf", "b.pdf"]))
    assert "a-2.pdf" in out and (ws / "a.pdf").read_bytes() == before      # an existing name gets -2


def test_only_an_enabled_skills_own_scripts_run(run_skill) -> None:
    _, tool = run_skill
    assert "no enabled skill" in str(tool(skill="docx", script="docx_to_pdf.py", args=["x.docx"]))
    for script in ("../../agent/cli/main.py", "merge_pdf", "x.py"):
        assert "has no script" in str(tool(skill="pdf", script=script, args=[])), script


def test_arguments_are_never_a_shell(run_skill) -> None:
    ws, tool = run_skill
    out = str(tool(skill="pdf", script="split_pdf.py", args=["x.pdf; echo pwned > pwned.txt"]))
    assert "error" in out.lower() and not (ws / "pwned.txt").exists()


def test_stop_ends_the_script(tmp_path) -> None:
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    started = time.monotonic()
    code, out = run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, stop.is_set)
    assert code is None and out == "stopped" and time.monotonic() - started < 5


def test_the_policy_sees_every_path(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.pdf").write_bytes(b"%PDF")
    args = ["out.pdf", "a.pdf:2-5", "--pages", "1-3", "--out-dir", "Parts", "C:/x/y.docx", "1-3"]
    assert [(p, spec, w) for _, p, spec, w in path_args(args)] == [
        ("out.pdf", "", False), ("a.pdf", ":2-5", False), ("Parts", "", True), ("C:/x/y.docx", "", False)]
    effects = skill_effects(args, lambda p: ws / p)
    assert ("create", ws / "out.pdf") in effects
    assert ("read", ws / "a.pdf") in effects and ("create", ws / "*") in effects   # its output may land beside it
    assert ("create", ws / "Parts" / "*") in effects


def test_a_skill_script_reading_atlas_data_is_refused(tmp_path, monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from agent.safety import rules
    from agent.safety.policy import ToolPolicy
    from agent.safety.protected import Protected
    from agent.safety.scope import Scope

    rules.load.cache_clear()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ws = tmp_path / ".data" / "chats" / "c1"
    ws.mkdir(parents=True)
    (tmp_path / ".data" / "atlas.db").write_text("x")
    scope = Scope(ws, folders=[], protected=Protected(root=tmp_path / "atlas", data=tmp_path / ".data",
                                                      mcp_config=tmp_path / "atlas" / "mcp.json",
                                                      venv=tmp_path / "atlas" / ".venv",
                                                      skills=tmp_path / "atlas" / "skills", workspace=ws))
    event = SimpleNamespace(tool_use={"name": "run_skill", "toolUseId": "t", "input": {
        "skill": "xlsx", "script": "xlsx_to_csv.py", "args": ["../../atlas.db.xlsx"]}},
        selected_tool=SimpleNamespace(tool_name="run_skill"), cancel_tool=False)
    asyncio.run(ToolPolicy(scope)._before(event))
    rules.load.cache_clear()
    assert event.cancel_tool and "Atlas" in event.cancel_tool
