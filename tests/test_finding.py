"""find_files / list_folder (agent/tools/finding.py) and copy_file / move_file (files.py),
and how the grid and the floor see them."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.safety.scope import Scope
from agent.tools.files import file_tools
from agent.tools.finding import finding_tools


@pytest.fixture
def tree(tmp_path) -> tuple[Path, Path]:
    """A workspace and one allowed folder like a user's home."""
    ws, docs = tmp_path / "ws", tmp_path / "home"
    for sub in ("Documents/Old", "Reports/2026/Q3", "Projects/Lumen/meetings/april", "node_modules/x", ".cache"):
        (docs / sub).mkdir(parents=True)
    ws.mkdir()
    (docs / "Documents" / "Resume - Pranav.pdf").write_bytes(b"%PDF")
    old = docs / "Documents" / "Old" / "Resume 2022.pdf"
    old.write_bytes(b"%PDF")
    os.utime(old, (old.stat().st_atime, old.stat().st_mtime - 10**8))
    for name in ("september-expenses.xlsx", "october-expenses.xlsx"):
        (docs / "Reports" / "2026" / "Q3" / name).write_bytes(b"PK")
    (docs / "Projects" / "Lumen" / "meetings" / "april" / "notes.txt").write_text("Public launch: June 14.")
    (docs / "node_modules" / "x" / "resume.js").write_text("")
    (docs / ".cache" / "resume.txt").write_text("")
    return ws, docs


def _find(ws: Path, docs: Path, store=None):
    scope = Scope(ws, folders=[docs])
    return finding_tools(scope, lambda p: scope.place(p), lambda p: p.as_posix(), store)


def test_finds_by_name_at_any_depth_newest_first_skipping_junk(tree) -> None:
    find, _ = _find(*tree)
    out = find(query="my resume")
    assert out.index("Resume - Pranav.pdf") < out.index("Resume 2022.pdf")   # newer first
    assert "node_modules" not in out and ".cache" not in out


def test_more_matching_words_rank_first_and_kind_filters(tree) -> None:
    find, _ = _find(*tree)
    out = find(query="october expenses spreadsheet")
    assert out.splitlines()[1].endswith(")") and "october-expenses.xlsx" in out.splitlines()[1]
    assert "Resume" not in find(query="resume", kind="xlsx")


def test_finds_by_folder_words_and_by_text_inside(tree) -> None:
    find, _ = _find(*tree)
    assert "notes.txt" in find(query="lumen meeting notes")
    assert "notes.txt" in find(query="public launch")                    # only in the text


def test_finds_an_ingested_document_by_what_it_says(tree, tmp_path) -> None:
    ws, docs = tree
    pdf = docs / "Documents" / "Resume - Pranav.pdf"

    class Store:
        def find_text(self, query):
            return [(str(pdf.resolve()), "Skills: Python, SQL and React.")]

    assert "Resume - Pranav.pdf" in _find(ws, docs, Store())[0](query="react sql")


def test_nothing_found_says_where_it_looked_and_not_the_web(tree) -> None:
    out = _find(*tree)[0](query="tax return 2025")
    assert "No file matching" in out and "web" in out


def test_list_folder_is_a_tree_with_counts_past_the_depth(tree) -> None:
    ws, docs = tree
    _, ls = _find(ws, docs)
    out = ls(path=str(docs / "Reports"), depth=1)
    assert "2026/" in out and "october-expenses.xlsx" in out        # small: shown deeper on its own
    for i in range(45):
        (docs / "Reports" / "2026" / "Q3" / f"sub{i}").mkdir()
        (docs / "Reports" / "2026" / "Q3" / f"sub{i}" / "x.txt").write_text("")
    assert "(1 items inside)" in ls(path=str(docs / "Reports"), depth=3)  # big: stops at the depth
    whole = ls()
    assert "your workspace" in whole and "Documents/" in whole and "node_modules" not in whole


def test_copy_and_move_never_replace_a_file(tmp_path) -> None:
    _, copy, move = file_tools(lambda p: tmp_path / p, lambda p: p.name)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    assert "already exists" in str(copy(path="a.txt", destination="b.txt"))
    assert "already exists" in str(move(path="a.txt", destination="b.txt"))
    assert (tmp_path / "b.txt").read_text() == "b"
    (tmp_path / "sub").mkdir()
    copy(path="a.txt", destination="sub")
    move(path="a.txt", destination="renamed.txt")
    assert (tmp_path / "sub" / "a.txt").exists() and (tmp_path / "renamed.txt").exists()
    assert not (tmp_path / "a.txt").exists()


def test_workspace_files_are_shown_by_name_and_the_variable_places_them(tmp_path) -> None:
    """The workspace's path holds a chat id the model copied wrong (2026-11-05)."""
    from agent.platform.winpaths import shown_in

    ws = tmp_path / "chats" / "e2adf397c87948ee8d241c8d62546a"
    (ws / "sub").mkdir(parents=True)
    shown = shown_in(ws)
    assert shown(ws / "report.docx") == "report.docx" and shown(ws / "sub" / "a.txt") == "sub/a.txt"
    assert shown(ws) == "$ATLAS_WORKSPACE" and "e2adf" not in shown(ws / "x")
    scope = Scope(ws, folders=[tmp_path / "home"])
    for form in ("$ATLAS_WORKSPACE/report.docx", "${ATLAS_WORKSPACE}/report.docx", "%ATLAS_WORKSPACE%/report.docx"):
        assert scope.place(form) == ws / "report.docx", form
