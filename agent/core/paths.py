"""Where things live on disk, anchored to the application root.

Every path in settings.json is relative to the application root, never to the
process's working directory. They used to resolve against the cwd, which meant
a backend started from `tests/` wrote a second database there, and snapshots
landed in `data/data/sessions` because `session.dir` repeated the data dir.

The root is `ATLAS_ROOT` when the CLI sets it, and otherwise the directory two
levels above this file -- which is the repository, wherever it was started from.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent.core.settings import Settings

ROOT = Path(os.environ.get("ATLAS_ROOT") or Path(__file__).resolve().parents[2]).resolve()


def resolve(path: str | Path) -> Path:
    """An absolute path, relative paths taken from the application root."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def data_dir(settings: Settings) -> Path:
    return resolve(settings.paths.data_dir)


def database(settings: Settings) -> Path:
    return data_dir(settings) / "atlas.db"


def sessions_dir(settings: Settings) -> Path:
    """Strands' snapshot storage. Relative to the data dir, not the root."""
    p = Path(settings.session.dir)
    return p if p.is_absolute() else data_dir(settings) / p


def chat_dir(settings: Settings, chat_id: str) -> Path:
    """One chat's uploads and the files the agent writes for it."""
    return data_dir(settings) / "chats" / chat_id


def skills_dir(settings: Settings) -> Path:
    return resolve(settings.skills.dir)


def mcp_config(settings: Settings) -> Path:
    return resolve(settings.mcp.config)


__all__ = [
    "ROOT",
    "chat_dir",
    "data_dir",
    "database",
    "mcp_config",
    "resolve",
    "sessions_dir",
    "skills_dir",
]
