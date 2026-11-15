"""Ask my folders (agent/ingest/indexer.py): the allowed folders' documents kept in the ingest store."""

from __future__ import annotations

import secrets
from pathlib import Path

from agent.ingest import indexer
from agent.ingest.indexer import OWNER, FolderIndex
from agent.ingest.store import Store


def _docx(path: Path, text: str) -> None:
    from docx import Document

    path.parent.mkdir(parents=True, exist_ok=True)
    d = Document()
    d.add_paragraph(text)
    d.save(str(path))


def test_documents_in_the_folders_are_found_by_what_they_say(tmp_path, monkeypatch) -> None:
    home = tmp_path / "Docs"
    _docx(home / "contracts" / "acme.docx", "Late fees of two percent apply after thirty days.")
    _docx(home / "node_modules" / "pkg.docx", "Late fees appear here too.")             # a junk folder
    _docx(home / "~$acme.docx", "Late fees in a Word lock file.")                      # Word's own temp file
    _docx(home / "huge.docx", "Late fees in a file too big to index. " + secrets.token_hex(200_000))
    monkeypatch.setattr(indexer, "MAX_BYTES", (home / "contracts" / "acme.docx").stat().st_size + 1000)
    store = Store(tmp_path / "parsed")
    index = FolderIndex(store, folders=lambda: [home], enabled=lambda: True)
    assert index.scan() == 1
    sha = store.identify(home / "contracts" / "acme.docx")
    assert store.wait(sha, lambda e: e["status"] == "ready", 30)
    assert [Path(p).name for p, _ in store.find_text("late fees")] == ["acme.docx"]
    assert store.owner_of(OWNER, sha[:12]) == sha


def test_a_chat_reading_an_indexed_file_lifts_text_only(tmp_path) -> None:
    store = Store(tmp_path / "parsed")
    doc = tmp_path / "a.docx"
    _docx(doc, "hello")
    sha = store.submit(doc, OWNER, text_only=True)
    assert sha in store.text_only
    store.submit(doc, "c1")
    assert sha not in store.text_only
