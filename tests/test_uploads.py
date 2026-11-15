"""Uploads into a chat's workspace, and how its files are served."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import settings_file

from server.app import create_app


@pytest.fixture
def client(tmp_path):
    path = settings_file(tmp_path)
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
    """`..` resolved to the chat folder's parent and the upload failed with a 500."""
    r = _upload(client, name)
    assert r.status_code == 200, r.text
    saved = Path(r.json()["path"])
    assert saved.parent == client.workspace and saved.is_file()


def test_a_part_without_a_filename_is_a_clear_error(client) -> None:
    assert _upload(client, "").status_code == 422          # not a file part; never a 500


def test_a_second_file_with_the_same_name_does_not_overwrite(client) -> None:
    """An earlier message's history pointed at a file a later upload replaced."""
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
    """An uploaded SVG or HTML opened from its chip must not run on Atlas's origin."""
    _upload(client, name, b"<svg onload='alert(1)'/>")
    r = client.get(f"/api/chats/{client.chat}/files/{name}")
    disposition = r.headers.get("content-disposition", "")
    assert ("attachment" not in disposition) is inline
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_an_upload_is_parsed_and_its_progress_can_be_asked(client) -> None:
    """A document is parsed at upload, and the composer polls /ingest for its progress."""
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



# ---------------------------------------------------- attachments and outside content --

def _stop(client, response) -> None:
    """A sent message starts a run (there is no model here): stop it so the fixture can close."""
    import time

    run = (response.json().get("run") or {}).get("id")
    if run:
        client.post(f"/api/runs/{run}/cancel")
        time.sleep(0.3)


def test_a_message_can_only_attach_files_of_its_own_chat(client, tmp_path) -> None:
    """The server opened whatever path the client sent back with a message (2026-11-12)."""
    secret = tmp_path / "private.png"
    secret.write_bytes(b"not yours")
    other = client.post("/api/chats", json={"title": ""}).json()["id"]
    theirs = client.post(f"/api/chats/{other}/files", files={"file": ("theirs.txt", b"x")}).json()
    url = f"/api/chats/{client.chat}/messages"
    for path in (str(secret), "../../pairing-token", theirs["path"], "missing.txt"):
        r = client.post(url, json={"text": "look", "files": [{"name": "private.png", "path": path}]})
        assert r.status_code == 422 and "not a file of this chat" in r.text, path
    assert client.get(f"/api/chats/{client.chat}").json()["turns"] == []      # nothing was sent

    mine = _upload(client, "mine.txt").json()
    r = client.post(url, json={"text": "read it", "files": [mine],
                               "refs": [{"file": "mine.txt", "path": str(secret), "quote": "q"}]})
    assert r.status_code == 200, r.text
    _stop(client, r)
    turn = r.json()["chat"]["turns"][0]
    assert turn["files"][0]["path"] == mine["path"] and "path" not in turn["refs"][0]


def test_bytes_from_the_side_panel_mark_the_chat_as_outside_content(client, tmp_path) -> None:
    def tainted() -> bool:
        return bool(client.get(f"/api/chats/{client.chat}").json().get("tainted"))

    _upload(client, "mine.txt")
    assert not tainted()                                    # a file picked in the web UI is the user's own
    token = (tmp_path / "data" / "pairing-token").read_text(encoding="utf-8").strip()
    panel = {"Origin": "chrome-extension://abc", "Authorization": f"Bearer {token}"}
    r = client.post(f"/api/chats/{client.chat}/files", files={"file": ("shot.jpg", b"x")}, headers=panel)
    assert r.status_code == 200 and tainted()


def test_importing_atlas_own_data_as_a_pdf_is_refused(client, tmp_path) -> None:
    data = tmp_path / "data"
    (data / "leak.pdf").write_bytes(b"%PDF-1.4 pretend")
    r = client.post(f"/api/chats/{client.chat}/files/import", json={"url": (data / "leak.pdf").as_uri()})
    assert r.status_code == 422 and "Atlas's own data" in r.text
    mine = tmp_path / "paper.pdf"
    mine.write_bytes(b"%PDF-1.4 mine")
    r = client.post(f"/api/chats/{client.chat}/files/import", json={"url": mine.as_uri()})
    assert r.status_code == 200 and r.json()["name"] == "paper.pdf"
    assert not client.get(f"/api/chats/{client.chat}").json().get("tainted")   # a local file is not outside content
