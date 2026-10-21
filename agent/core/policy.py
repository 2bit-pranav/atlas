"""Tool-call policy: everything Atlas checks before a tool runs, in one fixed order.

Strands calls hooks in registration order, so separate hooks would run in
whatever order `build_agent` happened to register them. Instead this is the one
place a tool call is inspected before it runs, as ordered steps:

    1. normalise   MCP servers get Windows paths, not `/c/Users/...`
    2. access      a path outside the workspace and the allowed folders asks
                   the user (or is refused when `access.ask_outside` is off)
    3. install     a shell command that installs anything asks the user
    4. sensitive   an MCP tool the user marked "ask" asks the user
    5. documents   `read`/`write`/`edit` on a .docx/.pdf/.xlsx is redirected
                   to the commands and tools that handle them

The first step that refuses ends the check; an approved step moves on to the
next. Everything after a tool runs (re-running a crashed tool, annotating a
failure, pushing back when the model gives up) is recovery and lives in
`resilience.py`.

Asking is the run's job: steps call `approver(kind, detail)`, which emits an
`approval_request` the UI shows as Allow / Deny and returns "allowed",
"denied" or "expired" (no answer within `approvals.timeout`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import BeforeToolCallEvent
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

from agent.core.approvals import Approver, is_install
from agent.core.documents import GUARDED
from agent.core.shell_env import drive_path, windows_path

logger = logging.getLogger(__name__)

#: Tools whose `path` argument is a file path.
FILE_TOOLS = {"read", "write", "edit", "create_document", "edit_document"}

#: Absolute Windows paths inside a shell command: `/c/...`, `C:/...` or `C:\\...`,
#: optionally quoted. POSIX system paths (`/tmp`, `/usr/bin`) are the shell's
#: own and are not checked.
_DRIVE = r"""(?:/[A-Za-z]/|[A-Za-z]:[/\\])"""
_SHELL_PATH = re.compile(
    rf'''"({_DRIVE}[^"]*)"|'({_DRIVE}[^']*)'|(?:^|(?<=[\s=]))({_DRIVE}[^\s"';|&<>]*)''')


def _shell_paths(command: str) -> list[str]:
    """Quoted paths whole (they may contain spaces), unquoted ones up to a space."""
    return [next(g for g in m if g) for m in _SHELL_PATH.findall(command)]


@dataclass
class Scope:
    """What a turn may touch without asking."""

    workspace: Path
    folders: list[Path] = field(default_factory=list)
    #: Read-only additions: the skills folder and the Python install that runs
    #: their scripts.
    readable: list[Path] = field(default_factory=list)

    def allows(self, path: Path, *, write: bool) -> bool:
        roots = [self.workspace, *self.folders] + ([] if write else self.readable)
        target = _absolute(path)
        return any(target == r or r in target.parents for r in map(_absolute, roots))


def _absolute(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


@dataclass
class Decision:
    """A step's verdict on one tool call."""

    #: Text sent back to the model as the tool result when the call is refused.
    refuse: str | None = None
    #: Replacement input (the normalise step).
    rewrite: dict[str, Any] | None = None


class ToolPolicy(HookProvider):
    """The ordered pre-call checks. One instance per turn's agent."""

    def __init__(
        self,
        scope: Scope,
        *,
        approver: Approver | None = None,
        ask_outside: bool = True,
        sensitive: Callable[[str], bool] | None = None,
        reader: Callable[[str], str | None] | None = None,
    ) -> None:
        self.scope = scope
        self.approver = approver
        self.ask_outside = ask_outside
        self.sensitive = sensitive or (lambda name: False)
        self.reader = reader
        #: Folders the user allowed during this turn: not asked again.
        self._granted: list[Path] = []
        self.steps: list[Callable[[BeforeToolCallEvent], Awaitable[Decision | None]]] = [
            self._normalise, self._access, self._install, self._sensitive, self._documents,
        ]

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)

    async def _before(self, event: BeforeToolCallEvent) -> None:
        for step in self.steps:
            decision = await step(event)
            if decision is None:
                continue
            if decision.rewrite is not None:
                event.tool_use = {**event.tool_use, "input": decision.rewrite}
            if decision.refuse is not None:
                event.cancel_tool = decision.refuse
                return

    # ----------------------------------------------------------------- steps --

    async def _normalise(self, event: BeforeToolCallEvent) -> Decision | None:
        """MCP servers are separate programs: give them Windows paths.

        The filesystem server read `/c/Users/x` as `C:\\c\\Users\\x` and refused
        it as outside its allowed folders.
        """
        if not isinstance(event.selected_tool, MCPAgentTool):
            return None
        current = event.tool_use.get("input")
        fixed = _rewrite(current)
        return Decision(rewrite=fixed) if fixed != current else None

    async def _access(self, event: BeforeToolCallEvent) -> Decision | None:
        name, args = event.tool_use.get("name", ""), event.tool_use.get("input") or {}
        for path, write in _paths_of(name, args, event.selected_tool):
            if self.scope.allows(path, write=write) or any(
                    g == _absolute(path) or g in _absolute(path).parents for g in self._granted):
                continue
            folder = _absolute(path) if _absolute(path).is_dir() else _absolute(path).parent
            if not self.ask_outside or self.approver is None:
                return Decision(refuse=(
                    f"{path} is outside the folders Atlas may use. Tell the user; they can add "
                    f"{folder} under Settings > Access."))
            decision = await self.approver("access", {
                "tool": name, "path": str(_absolute(path)), "folder": str(folder),
                "command": f"{name} {'writes' if write else 'reads'} {_absolute(path)}"})
            if decision != "allowed":
                return Decision(refuse=(
                    f"The user did not allow access to {folder}, so this call was not run. Do not "
                    "try to reach it another way; continue without it or tell the user what you need."))
            self._granted.append(folder)
        return None

    async def _install(self, event: BeforeToolCallEvent) -> Decision | None:
        if event.tool_use.get("name") != "shell":
            return None
        command = str((event.tool_use.get("input") or {}).get("command", ""))
        if not is_install(command):
            return None
        if self.approver is None:
            return Decision(refuse=("Installing needs the user's approval and no one can be asked "
                                    "here. Tell the user the exact command to run themselves."))
        decision = await self.approver("install", {"tool": "shell", "command": command})
        logger.info("install %s: %s", decision, command)
        if decision == "allowed":
            return None
        if decision == "expired":
            return Decision(refuse=("The user did not answer the install request in time, so it "
                                    "was not run. Do not retry it. Tell the user what you wanted to "
                                    "install and why, and that they can ask you again."))
        return Decision(refuse=("The user declined this install, so it was not run. Do not try to "
                                "install it another way. Continue without it, or explain what it was "
                                "needed for."))

    async def _sensitive(self, event: BeforeToolCallEvent) -> Decision | None:
        tool = event.selected_tool
        if not isinstance(tool, MCPAgentTool) or not self.sensitive(tool.tool_name):
            return None
        if self.approver is None:
            return Decision(refuse="This tool needs the user's approval and no one can be asked here.")
        args = event.tool_use.get("input") or {}
        decision = await self.approver("tool", {
            "tool": tool.tool_name, "command": f"{tool.tool_name} {_brief(args)}"})
        if decision == "allowed":
            return None
        return Decision(refuse=(f"The user did not allow {tool.tool_name} this time, so it was not "
                                "run. Do not call it again for this; tell the user what you meant to do."))

    async def _documents(self, event: BeforeToolCallEvent) -> Decision | None:
        """Keep the plain file tools off binary documents.

        `write`/`edit` would corrupt one; `read` returns nothing the model can
        use. Both are answered at once with what does work.
        """
        name = event.tool_use.get("name")
        if name not in ("read", "write", "edit"):
            return None
        path = str((event.tool_use.get("input") or {}).get("path", ""))
        ext = Path(path).suffix.lower()
        if ext not in GUARDED:
            return None
        if name == "read":
            command = self.reader(path) if self.reader else None
            return Decision(refuse=(
                f"`read` only handles text files and images; {Path(path).name} is a binary {ext} "
                + (f"file. Read it with: {command}" if command else "file. Use the matching skill's script.")
                + " To merge, split, combine or convert it, load its skill first: the scripts do that "
                  "in one call, without reading it."))
        what = "edit_document" if name == "edit" else "create_document"
        return Decision(refuse=(f"{Path(path).name} is a binary {ext} file; writing text into it would "
                                f"corrupt it. Use the `{what}` tool instead."))


# ---------------------------------------------------------------- helpers --


def _rewrite(value: Any) -> Any:
    if isinstance(value, str):
        return drive_path(value)
    if isinstance(value, list):
        return [_rewrite(v) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite(v) for k, v in value.items()}
    return value


def _paths_of(name: str, args: dict[str, Any], tool: Any) -> list[tuple[Path, bool]]:
    """The paths a call touches, and whether it writes. Relative paths are the workspace's."""
    out: list[tuple[Path, bool]] = []
    if name in FILE_TOOLS and isinstance(args.get("path"), str) and args["path"]:
        raw = args["path"]
        if raw.startswith("/") or Path(raw).is_absolute():
            out.append((Path(windows_path(raw)), name != "read"))
    elif name == "shell":
        for raw in _shell_paths(str(args.get("command", ""))):
            out.append((Path(windows_path(raw.rstrip(".,)"))), False))
    elif isinstance(tool, MCPAgentTool):
        for raw in _strings(args):
            if re.match(r"^(?:[A-Za-z]:[/\\]|/[A-Za-z]/)", raw):
                out.append((Path(windows_path(drive_path(raw))), True))
    return out


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


def _brief(args: dict[str, Any], limit: int = 200) -> str:
    import json

    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


__all__ = ["Approver", "Decision", "FILE_TOOLS", "Scope", "ToolPolicy"]
