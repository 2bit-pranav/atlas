"""The permission grid: where a call works, what it does, and whether it asks.

Every tool call, Atlas's own, the harness's, the shell's and MCP's, is
described the same way, as (place, action) pairs, and each pair is looked up
in the grid of the current mode:

    zone        workspace (this chat's folder), folders (Settings > Access),
                elsewhere, system (Windows, Program Files, a drive root)
                -- Atlas's own files are the floor, refused before this
    action      read < create < change < delete; run (a command that is not
                a plain read or write)
    mode        look (read only), ask (the default), work (changes in the
                folders without asking; deleting still asks)

A verdict is `run`, `ask` or `refuse`. Two rules hold in every mode: a delete
outside the workspace asks, and once the chat has read outside content (a web
page, a downloaded PDF, an untrusted MCP tool) every run, change and delete,
and every create outside the workspace, asks.

A shell target is placed with `~`, `$HOME` and `%USERPROFILE%` read as the
home folder. One that cannot be placed (another variable, a relative path
after a `cd`) is "elsewhere", so it asks: before this, such targets were
skipped, and `rm -rf ~/Downloads/*` passed every check (decisions.md,
2026-11-05).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.platform.winpaths import windows_path
from agent.safety.call_paths import _IMAGE, READ_TOOLS, _shell_paths, _trim
from agent.safety.scope import Scope, _absolute
from agent.safety.shell import classify

ZONES = ("workspace", "folders", "elsewhere", "system")
ACTIONS = ("read", "create", "change", "delete", "run")
MODES = ("look", "ask", "work")

R, A, X = "run", "ask", "refuse"
#: mode -> zone -> verdict per action, in ACTIONS order.
GRID: dict[str, dict[str, tuple[str, str, str, str, str]]] = {
    "look": {"workspace": (R, R, R, R, X), "folders": (R, X, X, X, X),
             "elsewhere": (A, X, X, X, X), "system": (A, X, X, X, X)},
    "ask": {"workspace": (R, R, R, R, A), "folders": (R, R, A, A, A),
            "elsewhere": (A, A, A, A, A), "system": (A, X, X, X, X)},
    "work": {"workspace": (R, R, R, R, R), "folders": (R, R, R, A, R),
             "elsewhere": (A, A, A, A, A), "system": (A, X, X, X, X)},
}

#: Atlas's own tools and the harness's file tools: what each does to its `path`.
TOOL_ACTIONS = {
    **{name: "read" for name in READ_TOOLS},
    "create_document": "create", "edit_docx": "change", "set_cell": "change",
    "edit": "change", "delete_file": "delete", "move_file": "change",
}
#: Tools that also create their `destination` (copy_file reads its `path`, move_file changes it).
DESTINATION_TOOLS = {"copy_file", "move_file"}

_HOME_FORMS = re.compile(r"^(?:~|\$HOME|\$\{HOME\}|%USERPROFILE%|\$USERPROFILE|\$\{USERPROFILE\})(?=$|[/\\])")
_SKILL_SCRIPT = re.compile(r"""^\s*(?:python3?|py)(?:\.exe)?\s+["']?\$\{?ATLAS_SKILLS\}?/""")


@dataclass(frozen=True)
class Effect:
    """One thing a call does: an action at a place (None: no path, the workspace)."""

    action: str
    path: Path | None = None
    #: What the user is shown on a card, e.g. the command.
    what: str = ""


def zone(path: Path | None, scope: Scope, action: str = "read") -> str:
    """Where a placed path is. Atlas's own files never get here (the floor).
    The readable roots (the skills, the Python install) are folders for reading only."""
    if path is None:
        return "workspace"
    target = _absolute(path)
    if _within(target, scope.workspace):
        return "workspace"
    if any(_within(target, f) for f in [*scope.folders, *(scope.readable if action == "read" else [])]):
        return "folders"
    return "system" if _system(target) else "elsewhere"


def verdict(mode: str, where: str, action: str) -> str:
    return GRID.get(mode, GRID["ask"])[where][ACTIONS.index(action)]


def effects(name: str, args: dict[str, Any], tool: Any, scope: Scope) -> list[Effect]:
    """What a call does, wherever it can be seen. Tools with no file effect
    (calculate, page tools, skills) have none."""
    from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

    out: list[Effect] = []
    raw = args.get("path")
    if name in TOOL_ACTIONS and isinstance(raw, str) and raw:
        out.append(Effect(TOOL_ACTIONS[name], scope.place(raw)))
        dest = args.get("destination")
        if name in DESTINATION_TOOLS and isinstance(dest, str) and dest:
            out.append(Effect("create", scope.place(dest)))
    elif name == "write" and isinstance(raw, str) and raw:
        target = scope.place(raw)
        out.append(Effect("change" if target.exists() else "create", target))
    if name == "create_document":
        for src in _IMAGE.findall(str(args.get("content", ""))):
            src = src.strip().strip("<>")
            if not src.startswith(("asset:", "http://", "https://", "data:")):
                p = Path(windows_path(src)) if src.startswith("/") else Path(src)
                out.append(Effect("read", p if p.is_absolute() else scope.workspace / p))
    if name == "shell":
        out += _shell(str(args.get("command", "")), scope)
    elif isinstance(tool, MCPAgentTool):
        notes = getattr(tool.mcp_tool, "annotations", None)
        action = ("read" if getattr(notes, "read_only_hint", False)
                  else "delete" if getattr(notes, "destructive_hint", False) else "change")
        for value in _strings(args):
            if re.match(r"^(?:[A-Za-z]:[/\\]|/[A-Za-z]/)", value):
                out.append(Effect(action, Path(windows_path(value))))
    return out


def _shell(command: str, scope: Scope) -> list[Effect]:
    parsed = classify(command)
    after_cd = any(e.program == "cd" for e in parsed.effects)
    out: list[Effect] = []
    skill = bool(_SKILL_SCRIPT.match(command))
    for e in parsed.effects:
        if e.kind in ("write", "delete"):
            for raw in e.paths:
                target = _place_shell(raw, scope, after_cd)
                action = "delete" if e.kind == "delete" else (
                    "change" if target is not None and target.exists() else "create")
                out.append(Effect(action, target, command))
        elif e.kind == "other" and not skill:
            out.append(Effect("run", None, command))
    # Paths a command only names (cat, a script's input or output) are read, or
    # written by a skill script: placed, so outside the folders asks.
    for raw in _shell_paths(command):
        out.append(Effect("create" if skill else "read", Path(windows_path(_trim(raw))), command))
    return out


def _place_shell(raw: str, scope: Scope, after_cd: bool) -> Path | None:
    """A shell target as a path, or None when it cannot be placed (asks)."""
    raw = raw.strip("\"'")
    raw = _HOME_FORMS.sub(lambda _m: Path.home().as_posix(), raw)
    if "$" in raw or "%" in raw or raw.startswith("~"):
        return None
    if raw.startswith("/") or Path(raw).is_absolute():
        return Path(windows_path(raw))
    return None if after_cd else scope.workspace / raw


def placed_or_elsewhere(effect: Effect, scope: Scope) -> str:
    """The zone, with an unplaceable target as "elsewhere"."""
    if effect.path is None and effect.action != "run":
        return "elsewhere"
    return zone(effect.path, scope, effect.action)


def _within(path: Path, root: Path) -> bool:
    root = _absolute(root)
    return path == root or root in path.parents


def _system(path: Path) -> bool:
    """Windows, Program Files, ProgramData, a drive root itself."""
    if path == Path(path.anchor):
        return True
    top = path.parts[1].lower() if len(path.parts) > 1 else ""
    return top in ("windows", "program files", "program files (x86)", "programdata")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


__all__ = ["ACTIONS", "GRID", "MODES", "TOOL_ACTIONS", "ZONES", "Effect", "effects", "placed_or_elsewhere",
           "verdict", "zone"]
