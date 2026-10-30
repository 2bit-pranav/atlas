"""Routes for the browser extension: pairing, the user's details, fill
suggestions, PDFs for its viewer, table export. The extension's origin is
refused on the routes that would hand it the token or the user's details."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from agent.extension import form_fill
from agent.extension.table_export import write_table
from server.schemas import (
    FillBody,
    ProfileBody,
    TableBody,
)
from server.security import EXTENSION_SCHEMES
from skills._shared import LinkError, open_link  # the one document-link resolver


def register(api: Any, state: Any, pairing: Any, ports: Any) -> None:
    # ------------------------------------------------------------ pairing --

    @api.get("/pairing")
    async def get_pairing(request: Request) -> dict[str, Any]:
        """The extension's token and the address it should use. Not for the extension itself."""
        if request.headers.get("origin", "").startswith(EXTENSION_SCHEMES):
            raise HTTPException(403, "the extension cannot read the pairing token")
        return {"token": pairing.token, "base": f"http://127.0.0.1:{ports.backend}"}

    @api.post("/pairing/reset")
    async def reset_pairing(request: Request) -> dict[str, Any]:
        """A new token: the extension has to be paired again."""
        if request.headers.get("origin", "").startswith(EXTENSION_SCHEMES):
            raise HTTPException(403, "the extension cannot reset the pairing token")
        return {"token": pairing.reset()}

    @api.get("/profile")
    async def get_profile(request: Request) -> dict[str, Any]:
        """The user's details for fill suggestions. The web UI's, never the extension's."""
        if request.headers.get("origin", "").startswith(EXTENSION_SCHEMES):
            raise HTTPException(403, "the extension cannot read your details")
        return {"text": form_fill.read_profile(state.settings)}

    @api.put("/profile")
    async def put_profile(body: ProfileBody, request: Request) -> dict[str, Any]:
        if request.headers.get("origin", "").startswith(EXTENSION_SCHEMES):
            raise HTTPException(403, "edit your details in Atlas, not in the extension")
        await asyncio.to_thread(form_fill.write_profile, state.settings, body.text)
        return {"text": body.text}

    @api.post("/extension/fill")
    async def fill(body: FillBody) -> dict[str, Any]:
        """Suggested values for a form's fields, from the user's details. Nothing is filled here."""
        try:
            return await asyncio.to_thread(form_fill.suggest, state.settings, body.fields, body.title)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/extension/pdf")
    async def open_pdf(url: str) -> Any:
        """A PDF's bytes for the Atlas PDF viewer: a local `file://` one, or a web one it could not fetch."""
        try:
            _name, source, data = await asyncio.to_thread(open_link, url, b"%PDF", "PDF")
        except LinkError as exc:
            raise HTTPException(422, str(exc)) from exc
        if source is not None:
            return FileResponse(source, media_type="application/pdf")
        return Response(content=data, media_type="application/pdf")

    @api.post("/extension/table")
    async def save_table(body: TableBody) -> dict[str, Any]:
        """A table from a web page, saved as xlsx or csv. Code only: no model involved."""
        try:
            path = await asyncio.to_thread(write_table, body.rows, body.title, body.url, body.format,
                                           body.folder)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"path": str(path), "rows": len(body.rows)}
