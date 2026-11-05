"""What a turn may touch without asking: its workspace and the allowed folders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.platform.winpaths import windows_path
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

    def place(self, raw: str) -> Path:
        """Where a file tool's `path` argument lands: an absolute path as given,
        a relative one where the tools put it (`placement.locate`, else the
        workspace). The access check runs on this, so `../` cannot slip past."""
        if raw.startswith("/") or Path(raw).is_absolute():
            return Path(windows_path(raw))
        return locate(raw, self.workspace, self.folders) or self.workspace / raw


def _absolute(path: Path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


__all__ = ["Scope"]
