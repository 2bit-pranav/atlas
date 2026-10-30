"""Atlas's own files: the floor under every other check.

An agent that can change Atlas can change what it is allowed to do: edit the
policy's code, add an MCP server (a command of its choosing) to `mcp.json`,
raise its own limits in `settings.json`. And the data folder holds what other
chats said, the extension's pairing token and the user's details. So:

- nothing in Atlas's folder, its venv or its data folder is ever **written**;
- nothing in the data folder is ever **read**, except the chats folder (every
  chat's workspace lives there), and `mcp.json` is never read (it holds keys).

Refused outright, never asked: the user allowing a folder that happens to
contain Atlas (their Desktop) does not allow this.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Protected:
    root: Path
    data: Path
    mcp_config: Path
    venv: Path | None = None
    skills: Path | None = None

    def refuses(self, path: Path, *, write: bool) -> str | None:
        """Why `path` is off limits for this access, or None."""
        target = _norm(path)
        if _inside(target, _norm(self.data / "chats")):
            return None  # every chat's workspace: the agent's own place to work
        if target == _norm(self.mcp_config) or _inside(target, _norm(self.data)):
            return (f"{path} is Atlas's own data (its settings, keys or other chats). The agent may not read "
                    "or change it, and the user cannot allow it. Continue without it.")
        if write and any(_inside(target, _norm(p)) for p in (self.root, self.venv, self.skills) if p is not None):
            return (f"{path} is Atlas's own file. The agent may not change Atlas itself; if a setting should "
                    "change, tell the user to change it in Settings.")
        return None


def _norm(path: Path) -> str:
    """Absolute, with links and `..` resolved: a junction cannot disguise a path."""
    return os.path.normcase(os.path.realpath(path))


def _inside(target: str, root: str) -> bool:
    return target == root or target.startswith(root.rstrip("\\/") + os.sep)
