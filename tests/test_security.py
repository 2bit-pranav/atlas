"""The request guard (server/security.py): who may call the API."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.security import Pairing, guard, trusted_origins

PORTS = SimpleNamespace(backend=8000, client=5173)


def _client(tmp_path, *, dev: bool) -> TestClient:
    app = FastAPI()
    app.middleware("http")(guard(Pairing(tmp_path / "pairing-token"), trusted_origins(PORTS, dev=dev)))

    @app.post("/api/mcp")
    def add_server() -> dict:
        return {"ok": True}

    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_vite_port_is_trusted_only_in_dev(tmp_path) -> None:
    """B6: any page on localhost:5173 (Vite's default for every project) could
    call the API, POST /api/mcp included, while the backend served the UI."""
    vite = {"Origin": "http://localhost:5173"}
    assert _client(tmp_path, dev=False).post("/api/mcp", headers=vite).status_code == 403
    assert _client(tmp_path, dev=True).post("/api/mcp", headers=vite).status_code == 200


def test_the_backends_own_origin_is_always_trusted(tmp_path) -> None:
    for dev in (False, True):
        client = _client(tmp_path, dev=dev)
        for origin in ("http://127.0.0.1:8000", "http://localhost:8000"):
            assert client.post("/api/mcp", headers={"Origin": origin}).status_code == 200


def test_other_sites_are_refused(tmp_path) -> None:
    client = _client(tmp_path, dev=True)
    assert client.post("/api/mcp", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/mcp", headers={"Origin": "http://localhost:3000"}).status_code == 403
    # An extension without the pairing token is refused too.
    assert client.post("/api/mcp", headers={"Origin": "chrome-extension://abc"}).status_code == 401
