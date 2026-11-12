"""Document links (skills/_shared.py: open_link): only public addresses, at every redirect."""

from __future__ import annotations

import http.server
import threading

import pytest

from skills._shared import LinkError, open_link


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - the base class's name
        if self.path.startswith("/go?"):
            self.send_response(302)
            self.send_header("Location", self.path[4:])
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"%PDF-1.4 a local document")

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def servers():
    made = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler) for _ in range(2)]
    for s in made:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield [f"127.0.0.1:{s.server_address[1]}" for s in made]
    for s in made:
        s.shutdown()


def test_a_link_to_this_computer_is_refused(servers, monkeypatch) -> None:
    """read_pdf and the PDF import fetch from the backend, which can reach Atlas's own API (2026-11-12)."""
    monkeypatch.delenv("ATLAS_LOCAL_LINKS", raising=False)
    for link in (f"http://{servers[0]}/a.pdf", "http://localhost:8000/api/chats", "http://[::1]:8000/x.pdf",
                 "http://192.168.1.1/router.pdf", "http://10.0.0.5/x.pdf"):
        with pytest.raises(LinkError, match="this computer or the local network"):
            open_link(link, b"%PDF", "PDF")


def test_a_redirect_is_checked_like_the_link(servers, monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LOCAL_LINKS", servers[0])          # as the live suite allows its own fixtures
    name, _source, data = open_link(f"http://{servers[0]}/a.pdf", b"%PDF", "PDF")
    assert name == "a.pdf" and data and data.startswith(b"%PDF")
    with pytest.raises(LinkError, match="this computer or the local network"):
        open_link(f"http://{servers[0]}/go?http://{servers[1]}/secret.pdf", b"%PDF", "PDF")
