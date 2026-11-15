"""Ask my folders: the documents in the allowed folders, kept in the ingest store.

`find_files` searched a document's words only if a chat had attached or read
it. Here a background thread keeps every PDF, Word and Excel file in the
allowed folders in the store, so "which contract mentions late fees?" finds it
by what it says:

- at start, every `INTERVAL` seconds, and at once when the folders change;
- the text layer only: a scanned page stays pending until a chat reads that file
  (`Store.submit(text_only=True)`), so indexing never means OCR-ing every scan;
- files the store already has, unchanged, cost a `stat` (it keys them by size and time);
- the folders `find_files` skips (dot folders, node_modules, ...), at most
  `MAX_FILES` files and none over `MAX_BYTES`.

Only the folders the user allowed (Settings > Access) are read, and the index
stays in Atlas's data folder; `find_files` still shows only paths in the folders.
shortcut: entries of a folder taken out of the list stay in the store (unseen,
since `find_files` filters by folder); drop them if the store's size matters.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.ingest.store import kind_of

logger = logging.getLogger(__name__)

INTERVAL = 600.0
MAX_FILES = 3000
MAX_BYTES = 50 * 1024 * 1024
#: The store's owner for what the index brought in.
OWNER = "_folders"


class FolderIndex:
    def __init__(self, store: Any, folders: Callable[[], list[Path]], enabled: Callable[[], bool],
                 interval: float = INTERVAL) -> None:
        self.store, self.folders, self.enabled, self.interval = store, folders, enabled, interval
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="atlas-folder-index", daemon=True)
            self._thread.start()

    def wake(self) -> None:
        """Scan now: the folders or the switch changed."""
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.enabled():
                try:
                    n = self.scan()
                    logger.info("folder index: %d document(s) in the allowed folders", n)
                except Exception:  # noqa: BLE001 - a bad folder must not end the thread
                    logger.warning("folder index scan failed", exc_info=True)
            self._wake.wait(self.interval)
            self._wake.clear()

    def scan(self) -> int:
        """Submit every document in the folders; returns how many were seen."""
        from agent.tools.finding import _skipped

        seen = 0
        for base in self.folders():
            for top, dirs, files in os.walk(base):
                if self._stop.is_set():
                    return seen
                dirs[:] = [d for d in dirs if not _skipped(d)]
                for name in files:
                    p = Path(top) / name
                    if kind_of(p) is None or name.startswith(("~$", ".")):
                        continue
                    try:
                        if p.stat().st_size > MAX_BYTES:
                            continue
                    except OSError:
                        continue
                    self.store.submit(p, OWNER, text_only=True)
                    seen += 1
                    if seen >= MAX_FILES:
                        return seen
        return seen


__all__ = ["OWNER", "FolderIndex"]
