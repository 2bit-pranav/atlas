"""Who may call the backend: the web UI, local tools, and the paired extension.

Anything listening on 127.0.0.1 can be reached by every web page the user
opens, so the API checks each request:

* **Host** must be 127.0.0.1 or localhost, which stops DNS rebinding (a site
  whose name resolves to 127.0.0.1 would otherwise count as same-origin).
* **Origin**, when the browser sends one: the web UI's own origins (the
  backend's port, and Vite's with `--dev`) pass; a browser extension must carry
  the pairing token; any other site is refused.
* A cross-site request without an Origin (an `<img>` or `no-cors` fetch) is
  refused too, unless it carries the token, which is how the extension loads
  images and files by URL.

Requests from local programs (curl, `atlas`) send no Origin and pass: they
already run as the user. The pairing token lives in `<data>/pairing-token`,
made on first start. "Connect" on the web UI's Browser extension page hands it
to the extension, which checks it against `/api/health` before keeping it. The extension sends it as `Authorization: Bearer`,
or as `?token=` where a URL is all it can give.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

EXTENSION_SCHEMES = ("chrome-extension://", "extension://", "moz-extension://")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


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
        given = given or request.query_params.get("token", "")
        return bool(given) and hmac.compare_digest(given, self.token)


def guard(pairing: Pairing, trusted_origins: set[str]):
    """The middleware: refuse what is not the web UI, a local tool or the paired extension."""

    async def middleware(request: Request, call_next):
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS:
            return JSONResponse({"detail": f"unexpected Host {host!r}"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in trusted_origins:
            if not origin.startswith(EXTENSION_SCHEMES):
                return JSONResponse({"detail": f"requests from {origin} are not allowed"}, status_code=403)
            if not pairing.valid(request):
                return JSONResponse({"detail": "not paired: connect the extension from the Browser "
                                     "extension page in Atlas"}, status_code=401)
        elif not origin and request.headers.get("sec-fetch-site") == "cross-site" and not pairing.valid(request):
            return JSONResponse({"detail": "cross-site requests are not allowed"}, status_code=403)
        return await call_next(request)

    return middleware


__all__ = ["Pairing", "guard"]
