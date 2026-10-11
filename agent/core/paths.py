"""Where Atlas keeps its files (spec section 3).

One place decides this, so the launcher, the backend and the tests agree.

    <data dir>/
        atlas.db          app state: chats, nodes, runs, events, catalog
        blobs/<sha256>    uploaded file bytes, stored once per distinct content
        duckdb/data.duckdb  every parsed table in the installation
        workspace/<chat_id>/  scratch/, outputs/ -- per-chat working files only

The split matters, and it was wrong at first. **Parsed data is global; working
files are per chat.** A spreadsheet parsed into DuckDB is keyed by its handle,
and handles are allocated globally (``next_handle`` counts every attachment, not
each chat's), so ``f1_mar`` already names one table in the whole installation.
Scoping the database per chat therefore bought nothing and cost correctness:
the same file uploaded to a second chat was deduplicated to the same attachment,
but its tables stayed in the first chat's database, so the second chat had a
file it could list and no data it could query.

Catalog objects stay per-chat -- a query result belongs to the conversation that
produced it, and section 11.4's branch visibility depends on that.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "ATLAS_DATA_DIR"
ENV_CHAT_DIR = "ATLAS_CHAT_DIR"
ENV_BLOB_DIR = "ATLAS_BLOB_DIR"
ENV_DUCK_DIR = "ATLAS_DUCK_DIR"


def resolve_data_dir() -> Path:
    """The app data directory. Override with ``ATLAS_DATA_DIR``."""
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.cwd() / "data").resolve()


def resolve_chat_dir() -> Path:
    """Where per-chat workspaces live. Override with ``ATLAS_CHAT_DIR``."""
    override = os.environ.get(ENV_CHAT_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return (resolve_data_dir() / "workspace").resolve()


def chat_workspace(chat_id: str) -> Path:
    return resolve_chat_dir() / chat_id


def resolve_blob_dir() -> Path:
    """Uploaded bytes, addressed by content hash. Override with ``ATLAS_BLOB_DIR``.

    Global on purpose: identical bytes are stored once, whichever chats use
    them. That is what makes deduplication mean something.
    """
    override = os.environ.get(ENV_BLOB_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return (resolve_data_dir() / "blobs").resolve()


def blob_path(sha256: str, suffix: str = "") -> Path:
    return resolve_blob_dir() / f"{sha256}{suffix}"


def resolve_duck_dir() -> Path:
    """The single DuckDB holding every parsed table. ``ATLAS_DUCK_DIR``."""
    override = os.environ.get(ENV_DUCK_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return (resolve_data_dir() / "duckdb").resolve()


def duck_path(name: str = "data") -> Path:
    return resolve_duck_dir() / f"{name}.duckdb"


def default_data_dir() -> Path:
    return resolve_data_dir()


__all__ = [
    "ENV_BLOB_DIR",
    "ENV_CHAT_DIR",
    "ENV_DATA_DIR",
    "ENV_DUCK_DIR",
    "blob_path",
    "chat_workspace",
    "default_data_dir",
    "duck_path",
    "resolve_blob_dir",
    "resolve_chat_dir",
    "resolve_data_dir",
    "resolve_duck_dir",
]
