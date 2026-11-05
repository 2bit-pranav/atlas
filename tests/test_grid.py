"""The permission grid (agent/safety/grid.py) through the policy: where a call
works, what it does, and whether it runs, asks or is refused, in each mode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import Asked, mcp_tool

from agent.safety.policy import ToolPolicy
from agent.safety.protected import Protected
from agent.safety.scope import Scope
from agent.tools.files import recycle


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A user's home with an allowed folder, Atlas's data folder and a chat workspace."""
    from agent.safety import rules

    rules.load.cache_clear()   # the floor's rules name the home folder, and are cached
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for sub in ("Docs", "Downloads", ".data/chats/c1", "atlas"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "Docs" / "notes.txt").write_text("keep")
    yield tmp_path
    rules.load.cache_clear()


def _policy(home: Path, mode: str = "ask", answer: str = "allowed", tainted: bool = False) -> tuple[ToolPolicy, Asked]:
    asked = Asked(answer)
    scope = Scope(home / ".data" / "chats" / "c1", folders=[home / "Docs"],
                  protected=Protected(root=home / "atlas", data=home / ".data", mcp_config=home / "atlas" / "mcp.json",
                                      venv=home / "atlas" / ".venv", skills=home / "atlas" / "skills"))
    return ToolPolicy(scope, approver=asked, mode=mode, tainted=lambda: tainted), asked


def _call(policy: ToolPolicy, name: str, args: dict, tool=None) -> str | bool:
    event = SimpleNamespace(tool_use={"name": name, "toolUseId": "t", "input": args},
                            selected_tool=tool or SimpleNamespace(tool_name=name), cancel_tool=False)
    asyncio.run(policy._before(event))
    return event.cancel_tool


@pytest.mark.parametrize("command", [
    "rm -rf ~/Downloads/*", "rm -rf $HOME/Downloads", "rm -rf ${HOME}/Downloads", "cd ~ && rm -rf Downloads",
    "rm -rf %USERPROFILE%/Downloads",
])
def test_deleting_through_home_forms_never_runs(home, command) -> None:
    """These passed every check: targets with `~` or a variable were skipped (2026-11-05)."""
    policy, asked = _policy(home)
    refused = _call(policy, "shell", {"command": command})
    assert refused and "delete_file" in refused and asked.calls == []


def test_shell_delete_of_the_users_files_is_refused_and_pointed_to_delete_file(home) -> None:
    policy, _ = _policy(home, mode="work")
    assert "delete_file" in _call(policy, "shell", {"command": f"rm {(home / 'Docs' / 'notes.txt').as_posix()}"})
    assert _call(policy, "shell", {"command": "rm scratch.txt"}) is False      # the workspace's own


@pytest.mark.parametrize("mode, where, action, expected", [
    ("ask", "Docs/notes.txt", "read_text", "run"),
    ("ask", "Docs/new.docx", "create_document", "run"),
    ("ask", "Docs/notes.txt", "edit", "ask"),
    ("ask", "Docs/notes.txt", "delete_file", "ask"),
    ("ask", ".data/chats/c1/out.txt", "delete_file", "run"),
    ("ask", "Elsewhere/x.txt", "read_text", "ask"),
    ("ask", "Elsewhere/x.txt", "create_document", "ask"),
    ("look", "Docs/notes.txt", "read_text", "run"),
    ("look", "Docs/new.docx", "create_document", "refuse"),
    ("look", "Docs/notes.txt", "edit", "refuse"),
    ("work", "Docs/notes.txt", "edit", "run"),
    ("work", "Docs/notes.txt", "delete_file", "ask"),
    ("work", "Elsewhere/x.txt", "edit", "ask"),
])
def test_the_grid(home, mode, where, action, expected) -> None:
    policy, asked = _policy(home, mode=mode, answer="denied")
    args = {"path": (home / where).as_posix(), "content": "x", "old_string": "a", "new_string": "b"}
    refused = _call(policy, action, args)
    got = "ask" if asked.calls else "refuse" if refused else "run"
    assert got == expected, (mode, where, action, refused)


def test_system_folders_are_read_with_a_card_and_never_changed(home) -> None:
    policy, asked = _policy(home)
    assert "system folder" in _call(policy, "edit", {"path": "C:/Windows/win.ini", "old_string": "a", "new_string": "b"})
    assert asked.calls == []
    _call(policy, "read_text", {"path": "C:/Windows/win.ini"})
    assert asked.calls and asked.calls[0][1]["action"] == "read"


def test_atlas_itself_is_the_floor_in_every_mode(home) -> None:
    for mode in ("look", "ask", "work"):
        policy, asked = _policy(home, mode=mode)
        assert "Atlas" in _call(policy, "delete_file", {"path": (home / ".data" / "atlas.db").as_posix()})
        assert "Atlas" in _call(policy, "delete_file", {"path": (home / "atlas" / "settings.json").as_posix()})
        assert asked.calls == []


def test_commands_ask_but_skill_scripts_run(home) -> None:
    policy, asked = _policy(home, answer="denied")
    assert _call(policy, "shell", {"command": "python -c \"print(1)\""})
    assert asked.calls[-1][0] == "tool"
    n = len(asked.calls)
    assert _call(policy, "shell", {"command": 'python "$ATLAS_SKILLS/pdf/scripts/merge_pdf.py" out.pdf a.pdf b.pdf'}) is False
    assert _call(policy, "shell", {"command": "ls -la"}) is False
    assert len(asked.calls) == n


def test_a_target_that_cannot_be_placed_asks(home) -> None:
    policy, asked = _policy(home, answer="denied")
    assert _call(policy, "shell", {"command": "echo hi > $SOMEWHERE/out.txt"})
    assert asked.calls and asked.calls[0][1]["zone"] == "elsewhere"


def test_one_allow_covers_the_same_action_in_the_same_folder_not_more(home) -> None:
    policy, asked = _policy(home)
    notes = (home / "Docs" / "notes.txt").as_posix()
    assert _call(policy, "edit", {"path": notes, "old_string": "a", "new_string": "b"}) is False
    assert _call(policy, "edit", {"path": notes, "old_string": "b", "new_string": "c"}) is False
    assert len(asked.calls) == 1                                   # the change was allowed for this turn
    _call(policy, "delete_file", {"path": notes})
    assert len(asked.calls) == 2 and asked.calls[-1][1]["action"] == "delete"   # a change grant is not a delete grant


def test_outside_content_makes_changes_ask_even_in_work_mode(home) -> None:
    policy, asked = _policy(home, mode="work", answer="denied", tainted=True)
    refused = _call(policy, "edit", {"path": (home / "Docs" / "notes.txt").as_posix(), "old_string": "a", "new_string": "b"})
    assert refused and asked.calls[-1][0] == "page"
    assert _call(policy, "read_text", {"path": (home / "Docs" / "notes.txt").as_posix()}) is False


def test_mcp_tools_by_their_servers_labels(home) -> None:
    policy, asked = _policy(home, answer="denied")
    path = (home / "Docs" / "notes.txt").as_posix()
    assert _call(policy, "list_directory", {"path": path}, mcp_tool("list_directory", read_only=True)) is False
    assert asked.calls == []
    assert _call(policy, "move_file", {"source": path}, mcp_tool("move_file"))   # unlabelled: may change it
    assert asked.calls[-1][1]["action"] == "change"


def test_recycle_moves_a_file_to_the_recycle_bin(tmp_path) -> None:
    target = tmp_path / "atlas-test-recycle.txt"
    target.write_text("restore me")
    recycle(target)
    assert not target.exists()
