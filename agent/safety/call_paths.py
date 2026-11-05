"""Which paths a tool call touches (file tools, shell, MCP), and the path
rewrites made before the checks see them."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

from agent.platform.winpaths import drive_path, windows_path
from agent.safety.scope import Scope

#: Tools whose `path` argument is a file path, and those of them that only read.
#: `copy_file` only reads its `path`; its `destination` is a write (below).
READ_TOOLS = {"read_text", "read_image", "read_pdf", "read_docx", "read_xlsx", "find_files", "list_folder",
              "copy_file"}
#: Tools that write their `path`: the access step asks for write access, the taint step
#: asks outside the workspace.
WRITE_TOOLS = {"write", "edit", "create_document", "edit_docx", "set_cell", "delete_file", "move_file"}
FILE_TOOLS = READ_TOOLS | WRITE_TOOLS


#: Absolute Windows paths inside a shell command: `/c/...`, `C:/...` or `C:\\...`,
#: optionally quoted. POSIX system paths (`/tmp`, `/usr/bin`) are the shell's
#: own and are not checked.
_DRIVE = r"""(?:/[A-Za-z]/|[A-Za-z]:[/\\])"""


_SHELL_PATH = re.compile(
    rf'''"({_DRIVE}[^"]*)"|'({_DRIVE}[^']*)'|(?:^|(?<=[\s=]))({_DRIVE}[^\s"';|&<>]*)''')


def _shell_paths(command: str) -> list[str]:
    """Quoted paths whole (they may contain spaces), unquoted ones up to a space."""
    return [next(g for g in m if g) for m in _SHELL_PATH.findall(command)]


# ---------------------------------------------------------------- helpers --


_QUOTED = re.compile(r"""("(?:[^"\\]|\\.)*"|'[^']*')""")


_BARE_DRIVE = re.compile(r"""(?<![\w/])([A-Za-z]):\\([^\s"'|;&<>()]*)""")


def _unbackslash(command: str) -> str:
    """Unquoted `C:\\Users\\x` in a bash command, as `C:/Users/x`.

    Bash takes a backslash outside quotes as an escape, so the model's
    `python C:\\Users\\...\\merge_pdf.py` ran as `C:UserspranaDesktop...` and failed.
    Forward slashes mean the same path to bash and to Windows programs. Quoted
    paths are left alone: there the backslashes survive.
    """
    parts = _QUOTED.split(command)
    for i in range(0, len(parts), 2):  # even parts are outside quotes
        parts[i] = _BARE_DRIVE.sub(lambda m: f"{m[1]}:/" + m[2].replace("\\", "/"), parts[i])
    return "".join(parts)


#: MCP argument names that hold a path (the filesystem server's, and common ones).
_PATH_KEYS = {"path", "paths", "source", "destination", "file", "filename", "directory", "dir"}


def _rewrite(value: Any) -> Any:
    if isinstance(value, str):
        return drive_path(value)
    if isinstance(value, list):
        return [_rewrite(v) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite(v) for k, v in value.items()}
    return value


def _paths_of(name: str, args: dict[str, Any], tool: Any, scope: Scope) -> list[tuple[Path, bool]]:
    """The paths a call touches, and whether it writes. Relative paths too: they
    are placed as the tool will place them (`Scope.place`), so `../x` is checked."""
    out: list[tuple[Path, bool]] = []
    if name in FILE_TOOLS and isinstance(args.get("path"), str) and args["path"]:
        out.append((scope.place(args["path"]), name not in READ_TOOLS))
    if name in ("copy_file", "move_file") and isinstance(args.get("destination"), str) and args["destination"]:
        out.append((scope.place(args["destination"]), True))
    if name == "create_document":
        # Images in the Markdown are files it reads and embeds: checked like any read,
        # or a document could carry any picture on the disk (or Atlas's own files).
        for src in _IMAGE.findall(str(args.get("content", ""))):
            src = src.strip().strip("<>")
            if src.startswith(("asset:", "http://", "https://", "data:")):
                continue  # asset: resolves only for the chat that owns it (ingest/store.py)
            p = Path(windows_path(src)) if src.startswith("/") else Path(src)
            out.append((p if p.is_absolute() else scope.workspace / p, False))  # as create() places it
    elif name == "shell":
        for raw in _shell_paths(str(args.get("command", ""))):
            out.append((Path(windows_path(_trim(raw))), False))
    elif isinstance(tool, MCPAgentTool):
        for raw in _strings(args):
            if re.match(r"^(?:[A-Za-z]:[/\\]|/[A-Za-z]/)", raw):
                out.append((Path(windows_path(drive_path(raw))), True))
    return out


#: A Markdown image's source: `![caption](source)`.
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _trim(raw: str) -> str:
    """Punctuation after a path in prose or a command (`a.txt,` `(x.pdf)` `end.`),
    never a path's own `..`: stripping it turned `allowed/..` into `allowed/`."""
    raw = raw.rstrip(",)")
    return raw[:-1] if raw.endswith(".") and not raw.endswith(("/.", "\\.", "..")) else raw


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    return []


__all__ = ["FILE_TOOLS"]
