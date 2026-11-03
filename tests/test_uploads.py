"""B13, B25: uploads into a chat's workspace, and how its files are served."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path):
    settings = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    settings["paths"] = {"data_dir": str(tmp_path / "data")}
    settings["mcp"]["config"] = str(tmp_path / "mcp.json")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    app = create_app(path)                    # no lifespan: nothing is started
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    c.chat = c.post("/api/chats", json={"title": ""}).json()["id"]
    c.workspace = tmp_path / "data" / "chats" / c.chat
    yield c
    app.state.atlas.close()


def _upload(client, name: str, data: bytes = b"x"):
    return client.post(f"/api/chats/{client.chat}/files", files={"file": (name, data)})


@pytest.mark.parametrize("name", ["..", ".", "CON", "a:b?.txt", "notes.txt. ", "../../escape.txt"])
def test_awkward_names_are_saved_safely(client, name) -> None:
    """B13: `..` resolved to the chat folder's parent and the upload failed with a 500."""
    r = _upload(client, name)
    assert r.status_code == 200, r.text
    saved = Path(r.json()["path"])
    assert saved.parent == client.workspace and saved.is_file()


def test_a_part_without_a_filename_is_a_clear_error(client) -> None:
    assert _upload(client, "").status_code == 422          # not a file part; never a 500


def test_a_second_file_with_the_same_name_does_not_overwrite(client) -> None:
    """B13: an earlier message's history pointed at a file a later upload replaced."""
    first = _upload(client, "report.pdf", b"first").json()
    second = _upload(client, "report.pdf", b"second").json()
    assert first["name"] == "report.pdf" and second["name"] == "report (2).pdf"
    assert Path(first["path"]).read_bytes() == b"first"


def test_an_upload_over_the_cap_is_refused(client, monkeypatch) -> None:
    import server.routes.files as files

    monkeypatch.setattr(files, "MAX_UPLOAD_BYTES", 10)
    r = _upload(client, "big.bin", b"x" * 100)
    assert r.status_code == 413
    assert not (client.workspace / "big.bin").exists()       # no partial file left behind


@pytest.mark.parametrize("name, inline", [("photo.png", True), ("drawing.svg", False), ("page.html", False)])
def test_only_raster_images_are_shown_inline(client, name, inline) -> None:
    """B25: an uploaded SVG or HTML opened from its chip must not run on Atlas's origin."""
    _upload(client, name, b"<svg onload='alert(1)'/>")
    r = client.get(f"/api/chats/{client.chat}/files/{name}")
    disposition = r.headers.get("content-disposition", "")
    assert ("attachment" not in disposition) is inline
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_an_upload_is_parsed_and_its_progress_can_be_asked(client) -> None:
    """Plan Phase 2 and 4: a document is parsed at upload; the composer polls /ingest."""
    import io
    import time

    from docx import Document

    buf = io.BytesIO()
    d = Document()
    d.add_paragraph("Hello")
    d.save(buf)
    _upload(client, "a.docx", buf.getvalue())
    _upload(client, "notes.txt", b"plain text is not parsed")
    url = f"/api/chats/{client.chat}/ingest?names=a.docx,notes.txt,../../escape.docx,missing.pdf"
    end = time.monotonic() + 20
    while (body := client.get(url).json()).get("a.docx", {}).get("status") != "ready" and time.monotonic() < end:
        time.sleep(0.2)
    assert body == {"a.docx": {"status": "ready", "done": 0, "total": 0}}   # the rest are left out

