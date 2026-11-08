"""Who may call the backend: the web UI, local tools, and the paired extension.

Anything listening on 127.0.0.1 can be reached by every web page the user
opens, so the API checks each request:

* **Host** must be 127.0.0.1 or localhost, which stops DNS rebinding (a site
  whose name resolves to 127.0.0.1 would otherwise count as same-origin).
* **Origin**, when the browser sends one: the web UI's own origins (the
  backend's port, and Vite's with `--dev`) pass; a browser extension must carry
  the pairing token; any other site is refused.
* A request without an Origin that a browser marks cross-site (an `<img>` or
  `no-cors` fetch) or `none` on a fetch (an extension's GET: Edge sends no
  Origin there) is refused too, unless it carries the token.
* A request let in by the token reaches only what the side panel uses
  (`EXTENSION_ROUTES`): never settings writes, MCP, skills, restart or pairing.

Requests from local programs (curl, `atlas`) send no Origin and pass: they
already run as the user. The pairing token lives in `<data>/pairing-token`,
made on first start. "Connect" on the web UI's Browser extension page hands it
to the extension, which checks it against `/api/health` before keeping it. The
extension sends it only as `Authorization: Bearer`, never in a URL (URLs end up
in history, logs and Referer headers); images and downloads are fetched.
"""

from __future__ import annotations

import hmac
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

EXTENSION_SCHEMES = ("chrome-extension://", "extension://", "moz-extension://")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

_ID = r"[^/]+"
#: What the paired extension may call: (methods, path). Everything else is the web UI's.
EXTENSION_ROUTES: list[tuple[set[str], re.Pattern[str]]] = [
    ({"GET"}, re.compile(r"/api/(health|settings)")),
    ({"GET", "POST"}, re.compile(r"/api/chats")),
    ({"GET", "PATCH", "DELETE"}, re.compile(rf"/api/chats/{_ID}")),
    ({"GET"}, re.compile(rf"/api/chats/{_ID}/workspace")),
    ({"POST"}, re.compile(rf"/api/chats/{_ID}/(messages|moments|files|files/import)")),
    ({"GET", "DELETE"}, re.compile(rf"/api/chats/{_ID}/files/.+")),
    ({"POST"}, re.compile(rf"/api/turns/{_ID}/(retry|edit|select)")),
    ({"GET"}, re.compile(rf"/api/runs/{_ID}(/events)?")),
    ({"POST"}, re.compile(rf"/api/runs/{_ID}/(approvals|calls)/{_ID}")),
    ({"POST"}, re.compile(rf"/api/runs/{_ID}/cancel")),
    ({"POST"}, re.compile(r"/api/extension/(fill|table)")),
    ({"GET"}, re.compile(r"/api/extension/pdf")),
    ({"GET"}, re.compile(r"/api/extension/basket(/b-[\w-]{8,40})?")),
]


def extension_may(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return True
    return any(method in methods and pattern.fullmatch(path) for methods, pattern in EXTENSION_ROUTES)


class Pairing:
    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            self.reset()

    @property
    def token(self) -> str:
        return self.path.read_text(encoding="utf-8").strip()

    def reset(self) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(24)
        self.path.write_text(token, encoding="utf-8")
        return token

    def valid(self, request: Request) -> bool:
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return bool(given) and hmac.compare_digest(given, self.token)


def trusted_origins(ports: Any, *, dev: bool) -> set[str]:
    """The web UI's own origins: the backend's port, and Vite's only in `--dev`.

    Vite's port (5173 by default) is every Vite project's default. Trusting it
    while the backend serves the UI itself gave any page on `localhost:5173`
    the whole API, `POST /api/mcp` (an arbitrary command) included.
    """
    allowed = [ports.backend, *([ports.client] if dev else [])]
    return {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in allowed}


def guard(pairing: Pairing, trusted_origins: set[str]):
    """The middleware: refuse what is not the web UI, a local tool or the paired extension."""

    async def middleware(request: Request, call_next):
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS:
            return JSONResponse({"detail": f"unexpected Host {host!r}"}, status_code=403)
        origin = request.headers.get("origin")
        site = request.headers.get("sec-fetch-site")
        if origin and origin not in trusted_origins and not origin.startswith(EXTENSION_SCHEMES):
            return JSONResponse({"detail": f"requests from {origin} are not allowed"}, status_code=403)
        if _needs_token(origin, site, request.headers.get("sec-fetch-mode")):
            if not pairing.valid(request):
                return JSONResponse({"detail": "not paired: connect the extension from the Browser "
                                     "extension page in Atlas"}, status_code=401)
            if not extension_may(request.method, request.url.path):
                return _outside_scope()
        return await call_next(request)

    return middleware


def _needs_token(origin: str | None, site: str | None, mode: str | None) -> bool:
    """Whether the request is the extension's (or could be another extension's).

    - an extension Origin (POSTs from an extension carry one);
    - no Origin and cross-site: an `<img>` or `no-cors` fetch from some page;
    - no Origin and `Sec-Fetch-Site: none` on a fetch, not a navigation: what
      Edge sends for an extension page's or worker's GET (measured). Without
      this, any installed extension allowed on all sites could read every
      chat, the profile and the pairing token itself.

    Local programs (curl, `atlas`) send no fetch metadata at all, and an address
    typed in the address bar is a navigation: neither needs the token.
    """
    if origin:
        return origin.startswith(EXTENSION_SCHEMES)
    return site == "cross-site" or (site == "none" and mode not in (None, "navigate"))


def _outside_scope() -> JSONResponse:
    return JSONResponse({"detail": "the extension cannot do this: use Atlas in the browser tab"}, status_code=403)


__all__ = ["EXTENSION_ROUTES", "Pairing", "extension_may", "guard"]
