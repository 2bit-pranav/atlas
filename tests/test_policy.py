"""The tool policy (agent/safety/policy.py): access, approvals, installs, taint,
the documents step and path rewrites; and skill requirement detection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import Asked, mcp_tool

from agent.integrations.skills import requirements as skill_requirements
from agent.safety.call_paths import _shell_paths
from agent.safety.policy import ToolPolicy
from agent.safety.scope import Scope


def _event(name: str, args: dict, tool=None, registered: bool = True) -> SimpleNamespace:
    """A call to `name`; `registered=False` is a tool the agent does not have."""
    if tool is None and registered:
        tool = SimpleNamespace(tool_name=name)
    return SimpleNamespace(tool_use={"name": name, "toolUseId": "t1", "input": args},
                           selected_tool=tool, cancel_tool=False)


def _run(policy: ToolPolicy, event) -> SimpleNamespace:
    asyncio.run(policy._before(event))
    return event


def _policy(tmp_path: Path, **kw) -> ToolPolicy:
    (tmp_path / "ws").mkdir(exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    return ToolPolicy(Scope(tmp_path / "ws", folders=[tmp_path / "docs"]), **kw)


def test_inside_scope_runs_without_asking(tmp_path) -> None:
    asked = Asked()
    policy = _policy(tmp_path, approver=asked)
    for path in (tmp_path / "ws" / "a.txt", tmp_path / "docs" / "sub" / "b.txt"):
        assert _run(policy, _event("write", {"path": path.as_posix()})).cancel_tool is False
    assert _run(policy, _event("write", {"path": "relative.txt"})).cancel_tool is False
    assert asked.calls == []


def test_outside_asks_once_per_folder(tmp_path) -> None:
    asked = Asked("allowed")
    policy = _policy(tmp_path, approver=asked)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert _run(policy, _event("read_text", {"path": (outside / "x.txt").as_posix()})).cancel_tool is False
    assert _run(policy, _event("read_text", {"path": (outside / "y.txt").as_posix()})).cancel_tool is False
    assert [k for k, _ in asked.calls] == ["access"]
    assert Path(asked.calls[0][1]["folder"]) == outside.resolve()


def test_outside_denied_or_not_askable_is_refused(tmp_path) -> None:
    target = {"path": (tmp_path / "x.txt").as_posix()}
    denied = _run(_policy(tmp_path, approver=Asked("denied")), _event("read_text", dict(target)))
    assert "did not allow" in denied.cancel_tool
    off = _run(_policy(tmp_path, approver=Asked(), ask_outside=False), _event("read_text", dict(target)))
    assert "Settings > Access" in off.cancel_tool


def test_readable_roots_are_read_only(tmp_path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    asked = Asked("denied")
    policy = ToolPolicy(Scope(tmp_path / "ws", readable=[skills]), approver=asked)
    assert _run(policy, _event("read_text", {"path": (skills / "pdf" / "SKILL.md").as_posix()})).cancel_tool is False
    assert _run(policy, _event("write", {"path": (skills / "x.md").as_posix()})).cancel_tool


def test_shell_paths_are_found_quoted_and_bare() -> None:
    cmd = 'python "/c/My Docs/a.py" --out=C:/tmp/o.txt \'D:\\x y\\z\' /tmp/ok | grep /usr/bin'
    assert _shell_paths(cmd) == ["/c/My Docs/a.py", "C:/tmp/o.txt", "D:\\x y\\z"]


def test_shell_outside_path_asks(tmp_path) -> None:
    asked = Asked("denied")
    event = _run(_policy(tmp_path, approver=asked), _event("shell", {"command": "dir C:/Windows/System32"}))
    assert event.cancel_tool and asked.calls[0][0] == "access"


def test_install_asks_and_respects_the_answer(tmp_path) -> None:
    for answer, refused in (("allowed", False), ("denied", "declined"), ("expired", "in time")):
        asked = Asked(answer)
        event = _run(_policy(tmp_path, approver=asked), _event("shell", {"command": "pip install openpyxl"}))
        assert asked.calls[0][0] == "install"
        assert (event.cancel_tool is False) if not refused else refused in event.cancel_tool
    no_one = _run(_policy(tmp_path), _event("shell", {"command": "npm install -g x"}))
    assert "run themselves" in no_one.cancel_tool


def test_mcp_paths_are_normalised_then_checked(tmp_path) -> None:
    asked = Asked()
    policy = _policy(tmp_path, approver=asked)
    inside = (tmp_path / "docs" / "n.txt").as_posix()          # C:/Users/... form
    git_bash = "/" + inside[0].lower() + inside[2:]            # /c/Users/... form
    event = _run(policy, _event("read_file", {"path": git_bash}, mcp_tool("read_file", read_only=True)))
    assert event.cancel_tool is False
    assert event.tool_use["input"]["path"].replace("\\", "/").lower() == inside.lower()
    assert asked.calls == []
    # A tool its server does not label read-only may change what it is given: it asks.
    _run(policy, _event("write_file", {"path": git_bash}, mcp_tool("write_file")))
    assert asked.calls and asked.calls[-1][1]["action"] == "change"


def test_sensitive_mcp_tool_asks(tmp_path) -> None:
    asked = Asked("denied")
    policy = _policy(tmp_path, approver=asked, sensitive=lambda name: name == "send_mail")
    assert _run(policy, _event("search", {"q": "x"}, mcp_tool("search"))).cancel_tool is False
    event = _run(policy, _event("send_mail", {"to": "a"}, mcp_tool("send_mail")))
    assert asked.calls[0][0] == "tool" and "did not allow" in event.cancel_tool


def test_documents_redirected_after_access(tmp_path) -> None:
    policy = _policy(tmp_path, approver=Asked())
    write = _run(policy, _event("write", {"path": "report.docx", "content": "x"}))
    assert "create_document" in write.cancel_tool
    # A denied access check refuses before the document step is reached.
    outside = _run(_policy(tmp_path, approver=Asked("denied")),
                   _event("read_text", {"path": (tmp_path / "x.pdf").as_posix()}))
    assert "did not allow" in outside.cancel_tool


def test_requirements_detected_from_all_three_sources(tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("pypdf>=4  # pdfs\n# comment\n-r other.txt\n")
    (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "^1"}}')
    (tmp_path / "SKILL.md").write_text(
        "Install:\n```bash\nnpm install -g agent-browser\npip install pypdf rich\n```\n"
        "Not in a fence: pip install ignored\n")
    found = {(r["manager"], r["package"], r["scope"]) for r in skill_requirements.detect(tmp_path)}
    assert found == {("pip", "pypdf>=4", "env"), ("npm", "left-pad", "skill"),
                     ("npm", "agent-browser", "global"), ("pip", "pypdf", "env"), ("pip", "rich", "env")}


def test_requirement_status_for_pip() -> None:
    status = skill_requirements.with_status(Path("."), [
        {"manager": "pip", "package": "pytest>=1", "scope": "env"},
        {"manager": "pip", "package": "surely-not-installed-xyz", "scope": "env"}])
    assert [r["installed"] for r in status] == [True, False]


# ------------------------------------------------------------ normalise --


def test_pasted_windows_path_works_in_file_tools(tmp_path) -> None:
    policy = _policy(tmp_path, approver=Asked())
    inside = str(tmp_path / "docs" / "notes.txt")                 # C:\Users\...\notes.txt
    event = _run(policy, _event("write", {"path": inside, "content": "x"}))
    assert event.cancel_tool is False
    assert event.tool_use["input"]["path"].startswith("/")        # /c/Users/... for the harness


def test_unquoted_backslash_paths_in_shell_become_forward_slashes(tmp_path) -> None:
    policy = _policy(tmp_path, approver=Asked())
    event = _run(policy, _event("shell", {"command": "dir docs && echo 'C:\\keep\this'"}))
    assert event.tool_use["input"]["command"] == "dir docs && echo 'C:\\keep\this'"
    inside = str(tmp_path / "docs")
    event = _run(policy, _event("shell", {"command": f"dir {inside}"}))
    assert "\\" not in event.tool_use["input"]["command"]


def test_relative_mcp_path_is_placed_in_an_allowed_folder(tmp_path) -> None:
    (tmp_path / "docs" / "Invoices").mkdir(parents=True)
    policy = _policy(tmp_path, approver=Asked())
    event = _run(policy, _event("list_directory", {"path": "Invoices"}, mcp_tool("list_directory")))
    assert event.tool_use["input"]["path"] == str(tmp_path / "docs" / "Invoices")


# ------------------------------------------------------------------ taint --


def test_after_reading_a_page_shell_and_outside_writes_ask(tmp_path) -> None:
    asked = Asked("denied")
    policy = _policy(tmp_path, approver=asked, tainted=lambda: True)
    shell = _run(policy, _event("shell", {"command": "echo hi"}))
    assert asked.calls[-1][0] == "page" and "outside content" in shell.cancel_tool
    write = _run(policy, _event("write", {"path": (tmp_path / "docs" / "x.txt").as_posix(), "content": "x"}))
    assert asked.calls[-1][0] == "page" and write.cancel_tool
    # The chat's own workspace stays writable.
    calls = len(asked.calls)
    assert _run(policy, _event("write", {"path": "notes.txt", "content": "x"})).cancel_tool is False
    assert len(asked.calls) == calls


def test_installs_still_ask_as_installs_when_tainted(tmp_path) -> None:
    asked = Asked("allowed")
    policy = _policy(tmp_path, approver=asked, tainted=lambda: True)
    assert _run(policy, _event("shell", {"command": "pip install rich"})).cancel_tool is False
    assert [k for k, _ in asked.calls] == ["install"]


# ------------------------------------------------------ B1, B2: escapes --


def test_relative_escape_from_the_workspace_asks(tmp_path) -> None:
    """B1: `../` in a relative path was never access-checked."""
    (tmp_path / "settings.json").write_text("{}")
    for name, args in (("create_document", {"path": "../settings.json.md", "content": "x"}),
                       ("edit_docx", {"path": "../settings.json", "block": "b1", "text": "x"}),
                       ("write", {"path": "../../x.txt", "content": "x"}),
                       ("read_text", {"path": "../settings.json"})):
        asked = Asked("denied")
        event = _run(_policy(tmp_path, approver=asked), _event(name, args))
        assert asked.calls and asked.calls[0][0] == "access", name
        assert "did not allow" in event.cancel_tool, name


def test_relative_paths_inside_scope_still_run_without_asking(tmp_path) -> None:
    (tmp_path / "docs" / "Reports").mkdir(parents=True)
    asked = Asked("denied")
    policy = _policy(tmp_path, approver=asked)
    for args in ({"path": "notes/x.txt", "content": "x"},                 # the workspace
                 {"path": "Reports/October.xlsx", "content": "| a |"}):   # an allowed folder
        assert _run(policy, _event("create_document", dict(args))).cancel_tool is False
    assert asked.calls == []


def test_locate_never_leaves_the_folder_it_searches(tmp_path) -> None:
    from agent.safety.placement import locate

    (tmp_path / "ws").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    assert locate("../secret.txt", tmp_path / "ws", []) is None
    assert locate("sub/../../secret.txt", tmp_path / "ws", []) is None


def test_trailing_dotdot_in_shell_is_not_stripped(tmp_path) -> None:
    """B2: `rstrip(".,)")` turned `allowed/..` into `allowed/`, which passed."""
    asked = Asked("denied")
    allowed = (tmp_path / "docs").as_posix()
    event = _run(_policy(tmp_path, approver=asked), _event("shell", {"command": f"rm -rf {allowed}/.."}))
    assert event.cancel_tool and "delete_file" in event.cancel_tool   # outside the workspace: never by shell
    # Ordinary punctuation after a path is still trimmed.
    asked = Asked("denied")
    event = _run(_policy(tmp_path, approver=asked), _event("shell", {"command": f"ls {allowed}/a.txt,"}))
    assert asked.calls == [] and event.cancel_tool is False


# ------------------------------------------------------- B9: exact grants --


def test_a_read_grant_does_not_allow_writes(tmp_path) -> None:
    """B9: approving a read granted the folder for writes too."""
    asked = Asked("allowed")
    policy = _policy(tmp_path, approver=asked)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert _run(policy, _event("read_text", {"path": (outside / "a.txt").as_posix()})).cancel_tool is False
    assert asked.calls[-1][1]["access"] == "read"
    _run(policy, _event("write", {"path": (outside / "b.txt").as_posix(), "content": "x"}))
    assert [k for k, _ in asked.calls] == ["access", "access"]      # the write asked again
    assert asked.calls[-1][1]["access"] == "write"
    # A write grant covers reads in that folder.
    _run(policy, _event("read_text", {"path": (outside / "c.txt").as_posix()}))
    assert len(asked.calls) == 2


def test_a_file_at_a_drive_root_or_home_grants_only_itself(tmp_path, monkeypatch) -> None:
    """B9: a read of C:/x.txt granted all of C:/."""
    home = tmp_path / "home"
    (home / "docs").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    asked = Asked("allowed")
    policy = _policy(tmp_path, approver=asked)
    first = (home / "a.txt").as_posix()
    _run(policy, _event("read_text", {"path": first}))
    assert Path(asked.calls[-1][1]["folder"]) == Path(first).resolve()   # the file, not the home folder
    _run(policy, _event("read_text", {"path": (home / "b.txt").as_posix()}))
    assert len(asked.calls) == 2                                      # a sibling asks again
    root = Path(tmp_path.anchor)
    _run(policy, _event("read_text", {"path": (root / "x.txt").as_posix()}))
    assert Path(asked.calls[-1][1]["folder"]) == (root / "x.txt").resolve()


@pytest.mark.parametrize("command", [
    "sed -i 's/23 days/18 days/' suppliers.docx",
    "echo hi > report.pdf",
    "cat notes.txt >> book.xlsx",
    "echo x | tee deck.pptx",
])
def test_shell_text_writes_into_binary_documents_are_refused(tmp_path, command) -> None:
    """The model ran `sed -i` on a .docx after edit_document failed, and destroyed it."""
    event = _run(_policy(tmp_path, approver=Asked()), _event("shell", {"command": command}))
    assert event.cancel_tool and "would corrupt it" in event.cancel_tool and "edit_docx" in event.cancel_tool


@pytest.mark.parametrize("command", [
    "cp a.pdf b.pdf",
    'python "$ATLAS_SKILLS/pdf/scripts/merge_pdf.py" out.pdf a.pdf b.pdf',
    "sed -i 's/a/b/' notes.txt",
])
def test_copies_scripts_and_text_edits_still_run(tmp_path, command) -> None:
    assert _run(_policy(tmp_path, approver=Asked()), _event("shell", {"command": command})).cancel_tool is False


def test_a_writing_tool_before_its_skill_says_which_skill_to_load(tmp_path) -> None:
    """Writing tools come with their skill (runtime/skill_tools.py)."""
    policy = _policy(tmp_path, approver=Asked())
    event = _run(policy, _event("set_cell", {"path": "a.xlsx", "cell": "B2", "value": "1"}, registered=False))
    assert 'skill_name="xlsx"' in event.cancel_tool
    unknown = _run(policy, _event("no_such_tool", {}, registered=False))
    assert unknown.cancel_tool is False                  # left to Strands' own "not found"


def test_edit_with_edit_docx_arguments_names_the_exact_call(tmp_path) -> None:
    """The model called `edit` with edit_docx's arguments, was refused, and gave up."""
    event = _run(_policy(tmp_path, approver=Asked()),
                 _event("edit", {"path": "suppliers.docx", "block": "t1.r3.c3", "text": "18 days"}))
    assert 'edit_docx(path="suppliers.docx", block="t1.r3.c3"' in event.cancel_tool


def test_create_document_images_are_reads_like_any_other(tmp_path) -> None:
    """An image line could embed any picture on the disk into a document unchecked."""
    outside = tmp_path / "Private"
    outside.mkdir()
    asked = Asked("denied")
    content = f"# Doc\n\n![x]({(outside / 'photo.png').as_posix()})\n"
    event = _run(_policy(tmp_path, approver=asked), _event("create_document", {"path": "out.docx", "content": content}))
    assert asked.calls and asked.calls[0][1]["access"] == "read" and "did not allow" in event.cancel_tool
    fine = "# Doc\n\n![a](chart.png)\n\n![b](asset:0123456789ab/p1-1.png)\n"
    assert _run(_policy(tmp_path, approver=Asked()),
                _event("create_document", {"path": "out.docx", "content": fine})).cancel_tool is False
