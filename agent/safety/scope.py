"""What a turn may touch without asking: its workspace and the allowed folders."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from agent.platform.winpaths import expand_workspace, windows_path
from agent.safety.placement import locate
from agent.safety.protected import Protected


@dataclass
class Scope:
    """What a turn may touch without asking."""

    workspace: Path
    folders: list[Path] = field(default_factory=list)
    #: Read-only additions: the skills folder and the Python install that runs
    #: their scripts.
    readable: list[Path] = field(default_factory=list)
    #: Atlas's own files, refused whatever the folders allow (protected.py).
    protected: Protected | None = None
    #: The files the user attached to this chat (`upload_key` of each). They sit in
    #: the workspace, where everything runs unasked: changing or deleting one asks.
    uploads: frozenset[str] = frozenset()

    def is_upload(self, path: Path) -> bool:
        return bool(self.uploads) and upload_key(path) in self.uploads

    def place(self, raw: str) -> Path:
        """Where a file tool's `path` argument lands: an absolute path as given,
        a relative one where the tools put it (`placement.locate`, else the
        workspace). The access check runs on this, so `../` cannot slip past.
        `$ATLAS_WORKSPACE/x` is the workspace's x, here as in the shell."""
        raw = expand_workspace(raw, self.workspace)
        if raw.startswith("/") or Path(raw).is_absolute():
            return Path(windows_path(raw))
        return locate(raw, self.workspace, self.folders) or self.workspace / raw


def upload_key(path: Path | str) -> str:
    """One spelling per file, so a path the model typed matches the one that was saved."""
    return os.path.normcase(os.path.realpath(path))


def _absolute(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


__all__ = ["Scope", "upload_key"]
