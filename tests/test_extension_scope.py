"""The extension's token opens what the side panel uses, nothing
more, and only as a header (server/security.py).

Before, the token opened the whole API: a leaked token could change settings,
add an MCP server (an arbitrary command) or install a skill. And it travelled
in `?token=` links, which end up in history, logs and Referer headers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import settings_file

from server.app import create_app


@pytest.fixture
def client(tmp_path):
    path = settings_file(tmp_path)
    app = create_app(path)
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    c.token = (tmp_path / "data" / "pairing-token").read_text(encoding="utf-8").strip()
    c.chat = c.post("/api/chats", json={"title": ""}).json()["id"]    # as the web UI
    yield c
    app.state.atlas.close()


def _ext(client) -> dict[str, str]:
    return {"Origin": "chrome-extension://abc", "Authorization": f"Bearer {client.token}"}


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/health"),
    ("GET", "/api/settings"),
    ("GET", "/api/chats"),
    ("GET", "/api/chats/{chat}"),
    ("GET", "/api/chats/{chat}/workspace"),
    ("GET", "/api/runs/nope"),
])
def test_the_panel_can_do_its_work(client, method, path) -> None:
    r = client.request(method, path.format(chat=client.chat), headers=_ext(client))
    assert r.status_code not in (401, 403), r.text


@pytest.mark.parametrize("method, path, body", [
    ("PUT", "/api/settings", {"access": {"ask_outside": False}}),
    ("POST", "/api/mcp", {"name": "x", "config": {"command": "atlas-test-no-such-program"}}),
    ("POST", "/api/skills/install", {"command": "o/repo"}),
    ("GET", "/api/skills", None),
    ("POST", "/api/restart", None),
    ("GET", "/api/pairing", None),
    ("PUT", "/api/profile", {"text": "x"}),
    ("POST", "/api/chats/import", {}),
    ("GET", "/api/chats/{chat}/export", None),
    ("GET", "/api/chats/{chat}/ingest", None),          # the web UI's composer only
    ("GET", "/api/outputs", None),                       # the home page: files across every chat
])
def test_everything_else_is_refused(client, method, path, body) -> None:
    r = client.request(method, path.format(chat=client.chat), headers=_ext(client), json=body)
    assert r.status_code == 403, r.text


def test_the_token_in_a_query_is_not_accepted(client) -> None:
    r = client.get(f"/api/chats?token={client.token}", headers={"Origin": "chrome-extension://abc"})
    assert r.status_code == 401


def test_a_cross_site_request_with_the_token_is_scoped_too(client) -> None:
    """No Origin (an extension fetch can omit it), but the token: still the extension's scope."""
    headers = {"Sec-Fetch-Site": "cross-site", "Authorization": f"Bearer {client.token}"}
    assert client.get("/api/chats", headers=headers).status_code == 200
    assert client.put("/api/settings", headers=headers, json={}).status_code == 403


def test_the_web_ui_is_not_limited(client) -> None:
    assert client.get("/api/skills", headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200


#: What Edge actually sends from an extension's page or worker on a GET (measured):
#: no Origin at all, and Sec-Fetch-Site "none".
EXTENSION_GET = {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "cors"}


@pytest.mark.parametrize("path", ["/api/chats", "/api/pairing", "/api/profile", "/api/mcp"])
def test_an_extension_get_without_origin_needs_the_token(client, path) -> None:
    """Any installed extension with access to all sites could read every chat,
    the profile and the pairing token itself: its GETs carry no Origin."""
    assert client.get(path, headers=EXTENSION_GET).status_code in (401, 403)


def test_an_extension_get_without_origin_is_scoped(client) -> None:
    with_token = {**EXTENSION_GET, "Authorization": f"Bearer {client.token}"}
    assert client.get("/api/chats", headers=with_token).status_code == 200
    assert client.get("/api/pairing", headers=with_token).status_code == 403
    assert client.get("/api/skills", headers=with_token).status_code == 403


def test_local_tools_and_typed_addresses_still_work(client) -> None:
    assert client.get("/api/skills").status_code == 200                       # curl, atlas
    navigate = {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"}      # typed in the address bar
    assert client.get("/api/health", headers=navigate).status_code == 200
