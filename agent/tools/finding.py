"""`find_files` and `list_folder`: finding the user's files without a path.

Made for a 2B model, which at baseline found 5 of 12 files (decisions.md,
2026-11-05): it asked the user for a path, listed one level per call, or
searched the web for its own notes. A shell `find` can do all of this, but
the model has to write the depth limits, the junk folders and the quoting
itself, and its output is uncapped. These take words, search every allowed
folder at any depth, and return a short ranked list with full paths, ready
for the read tools. They only read; the grid places a `path` given to them
like any read.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from strands import tool

from agent.safety.scope import Scope

#: Folders never searched: tool caches, version control, app data. Hidden ones too.
SKIP = {"node_modules", "__pycache__", "venv", "site-packages", "appdata", "$recycle.bin",
        "system volume information", "windows", "program files", "program files (x86)"}
#: Words that say nothing about which file is meant.
STOP = {"a", "an", "and", "the", "my", "me", "i", "of", "in", "on", "for", "to", "from", "is", "it", "that",
        "which", "what", "where", "find", "file", "files", "folder", "document", "doc", "with", "about", "all"}
#: `kind` words a model uses for a type, as extensions.
KINDS: dict[str, str] = {"spreadsheet": "xlsx xls xlsm csv", "excel": "xlsx xls xlsm", "word": "docx doc",
         "image": "png jpg jpeg gif webp", "picture": "png jpg jpeg gif webp", "text": "txt md",
         "presentation": "pptx ppt"}
TEXT = {".txt", ".md", ".csv", ".json", ".log", ".html", ".xml", ".yaml", ".yml", ".ini"}
MAX_RESULTS = 10
MAX_ENTRIES = 30_000          # files and folders looked at, per search
MAX_SECONDS = 4.0
MAX_TEXT_FILES, MAX_TEXT_BYTES = 400, 256 * 1024
MAX_LINES, PER_FOLDER = 120, 40


def _words(query: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOP]
    # "expenses" finds "expense", "meetings" finds "meeting": the stem is matched as a substring.
    return list(dict.fromkeys(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words))


def _kinds(kind: str) -> set[str]:
    out = set()
    for k in re.findall(r"[a-z0-9]+", kind.lower()):
        out.update((KINDS.get(k) or k).split())
    return {"." + k for k in out}


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 ** 2 else f"{n / 1024 ** 2:.1f} MB"


def _skipped(name: str) -> bool:
    return name.startswith(".") or name.lower() in SKIP


def _walk(bases: list[Path], never: list[Path]):
    """(base, file path, stat) for every file under the bases, within the limits."""
    seen, start = 0, time.monotonic()
    for base in bases:
        for top, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not _skipped(d) and (Path(top) / d) not in never)
            for name in files:
                seen += 1
                if seen > MAX_ENTRIES or time.monotonic() - start > MAX_SECONDS:
                    return
                p = Path(top) / name
                try:
                    yield base, p, p.stat()
                except OSError:
                    continue


def search_roots(scope: Scope, resolve: Callable[[str], Path], path: str = "") -> list[Path]:
    """Where a search looks: the given folder, else the workspace and every allowed folder."""
    return [p.resolve() for p in ([resolve(path)] if path else [scope.workspace, *scope.folders])]


def rank(scope: Scope, bases: list[Path], query: str, kind: str = "",
         store: Any = None) -> list[tuple[Path, dict[str, Any]]]:
    """Files under `bases` matching `query` (words in the name, folder or text) and `kind`, best
    first: most words matched, then in the name, then newest. Atlas's own data is never searched.
    Shared by find_files and the extension's file basket (agent/extension/form_fill.py)."""
    never = [p.resolve() for p in ((scope.protected.data, scope.protected.root) if scope.protected else ()) if p]
    words, kinds = _words(query), _kinds(kind)
    found: dict[Path, dict[str, Any]] = {}
    texts = 0
    for base, p, st in _walk([b for b in bases if b.is_dir()], never):
        if kinds and p.suffix.lower() not in kinds:
            continue
        name = p.stem.lower()
        where = str(p.parent.relative_to(base)).lower() if p.parent != base else ""
        hits_name = {w for w in words if w in name}
        hits = hits_name | {w for w in words if w in where}
        if (p.suffix.lower() in TEXT and len(hits) < len(words) and texts < MAX_TEXT_FILES
                and st.st_size <= MAX_TEXT_BYTES):
            texts += 1
            try:
                body = p.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                body = ""
            hits |= {w for w in words if w in body}
        if hits or (not words and kinds):
            found[p] = {"hits": hits, "name": len(hits_name), "mtime": st.st_mtime, "size": st.st_size}
    if store is not None and words:
        for doc, text in store.find_text(" ".join(words)):
            p = Path(doc)
            if (kinds and p.suffix.lower() not in kinds) or not p.is_file() or not any(
                    b in p.parents for b in bases):
                continue
            entry = found.setdefault(p, {"hits": set(), "name": 0, "mtime": p.stat().st_mtime,
                                         "size": p.stat().st_size})
            entry["hits"] = entry["hits"] | {w for w in words if w in text.lower()}
    return sorted(found.items(), key=lambda kv: (-len(kv[1]["hits"]), -kv[1]["name"], -kv[1]["mtime"]))


def finding_tools(scope: Scope, resolve: Callable[[str], Path], shown: Callable[[Path], str],
                  store: Any = None) -> list[Any]:
    """`scope` gives the folders to search; `store` (the ingest store) the text of
    documents already read, so a PDF can be found by what it says."""
    never = [p.resolve() for p in ((scope.protected.data, scope.protected.root) if scope.protected else ()) if p]

    def roots(path: str) -> list[Path]:
        return search_roots(scope, resolve, path)

    def pruned(folder: Path) -> bool:
        return any(folder == p for p in never)

    @tool(name="find_files")
    def find_files(query: str, path: str = "", kind: str = "") -> Any:
        """Find the user's files by words in their name, folder or contents, in every folder you may use.

        Use this whenever the user mentions one of their files without giving its path
        ("my resume", "the October expenses sheet", "notes from the Lumen meeting").
        Never search the web for the user's own files. Then read a result with its read tool.

        Args:
            query: Words that describe the file, e.g. "october expenses" or "invoice brightline".
            path: Optional folder to search in. Leave empty to search all of them.
            kind: Optional file type, e.g. "pdf", "xlsx", "spreadsheet", "word", "image".
        """
        words, kinds = _words(query), _kinds(kind)
        if not words and not kinds:
            return "Give find_files some words from the file's name or contents, e.g. query=\"october expenses\"."
        bases = roots(path)
        missing = [b for b in bases if not b.is_dir()]
        if path and missing:
            return f"Error: there is no folder {shown(missing[0])}. Call list_folder() to see the folders."
        ranked = rank(scope, bases, query, kind, store)
        found = dict(ranked)
        if not found:
            places = ", ".join(shown(b) for b in bases)
            return (f"No file matching {query!r}{f' of type {kind}' if kind else ''} in {places}. Try fewer or "
                    "other words, or list_folder() to look around. If it is not there, tell the user; do not "
                    "search the web for it.")
        lines = [f"{len(found)} file(s) found, best first:" if len(found) <= MAX_RESULTS
                 else f"{len(found)} files found; the best {MAX_RESULTS}:"]
        for p, e in ranked[:MAX_RESULTS]:
            matched = f"matches: {', '.join(sorted(e['hits']))}" if words else ""
            when = datetime.fromtimestamp(e["mtime"]).strftime("%d %b %Y")
            lines.append(f"- {shown(p)}  ({_size(e['size'])}, {when}{'; ' + matched if matched else ''})")
        if words and len(ranked) > 1 and len(ranked[0][1]["hits"]) < len(words):
            lines.append("No file matches every word; check the best one is the right file before using it.")
        return "\n".join(lines)

    @tool(name="list_folder")
    def list_folder(path: str = "", depth: int = 2) -> Any:
        """Show what is in a folder as a tree, subfolders included, with sizes and dates.

        Leave path empty to see every folder you may use. To find a file by name, find_files is faster.

        Args:
            path: The folder, e.g. "Reports" or its full path. Empty for all your folders.
            depth: How many levels of subfolders to show (1 to 4).
        """
        depth = max(1, min(int(depth or 2), 4))
        bases = roots(path)
        if path and not bases[0].is_dir():
            return (f"Error: {shown(bases[0])} is not a folder. Call list_folder() to see the folders, or "
                    "find_files to find a file by name.")
        lines: list[str] = []

        def tree(folder: Path, level: int, indent: str) -> None:
            try:
                entries = sorted(os.scandir(folder), key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError as exc:
                lines.append(f"{indent}(cannot open: {exc.strerror})")
                return
            entries = [e for e in entries if not _skipped(e.name) and not pruned(Path(e.path))]
            for i, e in enumerate(entries):
                if len(lines) >= MAX_LINES:
                    return
                if i == PER_FOLDER:
                    lines.append(f"{indent}... {len(entries) - i} more; list_folder(path=\"{shown(folder)}\") "
                                 "with a smaller depth, or find_files")
                    return
                if e.is_dir():
                    if level < depth:
                        lines.append(f"{indent}{e.name}/")
                        tree(Path(e.path), level + 1, indent + "  ")
                    else:
                        try:
                            n = sum(1 for _ in os.scandir(e.path))
                        except OSError:
                            n = 0
                        lines.append(f"{indent}{e.name}/  ({n} items inside)")
                else:
                    try:
                        st = e.stat()
                        lines.append(f"{indent}{e.name}  ({_size(st.st_size)}, "
                                     f"{datetime.fromtimestamp(st.st_mtime):%d %b %Y})")
                    except OSError:
                        lines.append(f"{indent}{e.name}")

        def render() -> None:
            lines.clear()
            for i, base in enumerate(bases):
                label = "your workspace for this chat" if not path and i == 0 else ""
                lines.append(f"{shown(base)}/" + (f"  ({label})" if label else ""))
                if base.is_dir():
                    tree(base, 1, "  ")

        render()
        # A small tree is shown deeper on its own: shown `Q3/ (2 items inside)`, the model
        # answered with the folder names and never looked in (2026-11-05).
        while depth < 4 and len(lines) < MAX_LINES // 3 and any(ln.endswith("items inside)") for ln in lines):
            depth += 1
            render()
        if len(lines) >= MAX_LINES:
            lines.append(f"(stopped at {MAX_LINES} lines: list a subfolder, or use find_files)")
        return "\n".join(lines)

    return [find_files, list_folder]


__all__ = ["finding_tools"]
