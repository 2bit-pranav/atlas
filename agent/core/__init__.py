"""L2: persistence core - schema, migrations, repositories and tree operations.

Import :func:`open_repo` rather than wiring ``Database`` + ``migrate`` + ``Repo``
by hand; it is the only composition the rest of the codebase needs.
"""

from __future__ import annotations

from pathlib import Path

from agent.core.db import Database
from agent.core.errors import (
    AtlasError,
    BadRequest,
    NotFound,
    ParentNotAccepting,
    RunActive,
    RunFinished,
    TerminalEventExists,
)
from agent.core.migrations import MIGRATIONS, current_version, migrate, pending
from agent.core.paths import default_data_dir, resolve_data_dir
from agent.core.repo import (
    ACTIVE_STATUSES,
    TERMINAL_EVENT_TYPES,
    CatalogObject,
    Chat,
    Event,
    Node,
    Repo,
    Run,
    Step,
    TreeNode,
)

DEFAULT_DB_NAME = "atlas.db"


def open_repo(db_path: Path | str | None = None) -> Repo:
    """Open (creating and migrating as needed) the app database."""
    if db_path is None:
        db_path = default_data_dir() / DEFAULT_DB_NAME
    db = Database(db_path)
    migrate(db.connection)
    return Repo(db)


__all__ = [
    "ACTIVE_STATUSES",
    "DEFAULT_DB_NAME",
    "MIGRATIONS",
    "TERMINAL_EVENT_TYPES",
    "AtlasError",
    "BadRequest",
    "CatalogObject",
    "Chat",
    "Database",
    "Event",
    "Node",
    "NotFound",
    "ParentNotAccepting",
    "Repo",
    "Run",
    "RunActive",
    "RunFinished",
    "Step",
    "TerminalEventExists",
    "TreeNode",
    "current_version",
    "default_data_dir",
    "migrate",
    "open_repo",
    "pending",
    "resolve_data_dir",
]
