"""The built web UI, served on the API's own port (a redirect to Vite in --dev)."""


from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from agent.config import paths


def _serve_client(app: FastAPI) -> None:
    """The built web UI (`client/dist`), on the API's own port and origin.

    `atlas start` uses this instead of the Vite dev server, so normal use needs
    no Node. Any path that is not a file in the build gets `index.html`, so a
    reload on `/settings/agent` still opens the app. Registered after the API,
    whose routes win. Looked up per request: `atlas start` may still be
    building it when the backend comes up. With `--dev` (ATLAS_DEV_UI set),
    pages redirect to Vite, so the backend's port never shows a stale build.
    """
    dist = paths.ROOT / "client" / "dist"
    dev_ui = os.environ.get("ATLAS_DEV_UI")

    @app.get("/{path:path}", include_in_schema=False)
    async def client(path: str, request: Request) -> Any:
        if path.startswith("api/"):
            raise HTTPException(404, f"no route /{path}")
        if dev_ui:  # `atlas start --dev`: the live UI is Vite's, on its own port
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"{dev_ui}/{path}{query}")
        if not (dist / "index.html").is_file():
            raise HTTPException(503, "The web UI is not built: run `npm run build` in client/, or `atlas start --dev`.")
        target = (dist / path).resolve()
        if path and target.is_file() and dist.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(dist / "index.html")


__all__ = []
