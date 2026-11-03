"""B32: Atlas's own files are on the floor (agent/safety/protected.py).

The agent can never change Atlas itself (its code, settings.json, mcp.json,
the venv, the skills), never read the data folder (the chat database,
snapshots, the pairing token, the user's details) except the chats folder,
and never read mcp.json (it holds keys). Refused outright, with no card,
even when the folder is allowed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent.safety.policy import ToolPolicy
from agent.safety.protected import Protected
from agent.safety.scope import Scope


class _Asked:
    def __init__(self, answer: str = "allowed") -> None:
        self.answer, self.calls = answer, []

    async def __call__(self, kind: str, detail: dict) -> str:
        self.calls.append(kind)
        return self.answer


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "Desktop" / "atlas"
    data = root / ".data"
    workspace = data / "chats" / "c1"
    for d in (workspace, data / "sessions", root / "agent", root / "skills" / "pdf", root / ".venv"):
        d.mkdir(parents=True)
    protected = Protected(root=root, data=data, mcp_config=root / "mcp.json", venv=root / ".venv")
    # The whole Desktop is an allowed folder, as on the user's machine.
    scope = Scope(workspace, folders=[tmp_path / "Desktop"], protected=protected)
    return SimpleNamespace(root=root, data=data, workspace=workspace, scope=scope)


def _run(scope: Scope, name: str, args: dict, approver=None):
    event = SimpleNamespace(tool_use={"name": name, "toolUseId": "t", "input": args},
                            selected_tool=None, cancel_tool=False)
    asyncio.run(ToolPolicy(scope, approver=approver or _Asked())._before(event))
    return event


@pytest.mark.parametrize("name, rel, content", [
    ("write", "agent/safety/policy.py", "x"),
    ("edit", "settings.json", None),
    ("create_document", "mcp.json.md", "x"),
    ("write", "skills/pdf/SKILL.md", "x"),
    ("write", ".venv/Lib/x.py", "x"),
    ("write", ".data/atlas.db", "x"),
])
def test_atlas_itself_is_never_written(layout, name, rel, content) -> None:
    asked = _Asked()
    args = {"path": (layout.root / rel).as_posix(), "content": content or "x"}
    if name == "edit":
        args = {"path": args["path"], "old_string": "a", "new_string": "b"}
    event = _run(layout.scope, name, args, asked)
    assert event.cancel_tool and "Atlas's own" in event.cancel_tool
    assert asked.calls == []                                # refused outright, never asked


@pytest.mark.parametrize("rel", [".data/pairing-token", ".data/profile.md", ".data/atlas.db",
                                 ".data/sessions/s/x.json", "mcp.json"])
def test_secrets_are_never_read(layout, rel) -> None:
    event = _run(layout.scope, "read_text", {"path": (layout.root / rel).as_posix()})
    assert event.cancel_tool and "Atlas's own" in event.cancel_tool


def test_shell_and_relative_paths_are_caught_too(layout) -> None:
    token = (layout.data / "pairing-token").as_posix()
    assert _run(layout.scope, "shell", {"command": f"cat {token}"}).cancel_tool
    # From the workspace (.data/chats/c1), ../../pairing-token is the token.
    assert _run(layout.scope, "read_text", {"path": "../../pairing-token"}).cancel_tool


def test_the_chats_folder_and_atlas_code_reads_still_work(layout) -> None:
    assert _run(layout.scope, "write", {"path": "notes.txt", "content": "x"}).cancel_tool is False
    other_chat = (layout.data / "chats" / "c2" / "a.txt").as_posix()
    assert _run(layout.scope, "read_text", {"path": other_chat}).cancel_tool is False
    code = (layout.root / "agent" / "x.py").as_posix()
    assert _run(layout.scope, "read_text", {"path": code}).cancel_tool is False
    # Elsewhere on the allowed Desktop: unaffected.
    desk = (layout.root.parent / "report.docx").as_posix()
    assert _run(layout.scope, "create_document", {"path": desk, "content": "x"}).cancel_tool is False


def test_without_protection_nothing_changes(tmp_path) -> None:
    scope = Scope(tmp_path / "ws", folders=[tmp_path])
    assert _run(scope, "write", {"path": (tmp_path / "x.txt").as_posix(), "content": "x"}).cancel_tool is False


@pytest.mark.parametrize("command", [
    "rm -rf ../..",                       # .data: the database, snapshots, the token
    "rm -rf ..",                          # every chat
    "rm -rf ../c2",                       # another chat
    "echo x > ../c2/notes.txt",
    "cp evil.py ../../../agent/x.py",     # Atlas's own code
    "format C: /q",                       # the floor's rules
])
def test_shell_commands_cannot_reach_atlas_or_other_chats(layout, command) -> None:
    """The workspace is .data/chats/<id>: a relative path in a shell command
    reached the data folder and other chats, and no check saw it."""
    asked = _Asked()
    event = _run(layout.scope, "shell", {"command": command}, asked)
    assert event.cancel_tool and asked.calls == [], command


@pytest.mark.parametrize("command", ["rm -rf build", "echo x > out/notes.txt", "rm -rf ./old", "ls .."])
def test_shell_commands_in_the_workspace_pass(layout, command) -> None:
    assert not _run(layout.scope, "shell", {"command": command}).cancel_tool, command
