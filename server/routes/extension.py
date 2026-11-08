"""Routes for the browser extension: pairing, the user's details, fill
suggestions, PDFs for its viewer, table export. The extension's origin is
refused on the routes that would hand it the token or the user's details."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from agent.extension import basket, form_fill, moments
from agent.store.chats import COMPLETED
from agent.extension.table_export import write_table
from server.schemas import (
    FillBody,
    MomentsBody,
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

    @api.post("/chats/{chat_id}/moments")
    async def key_moments(chat_id: str, body: MomentsBody) -> dict[str, Any]:
        """A video's key moments, saved as a finished turn of the chat: no agent run, no streaming.

        From the description's chapters when it has them (no model), else one
        model call over the transcript (`agent/extension/moments.py`)."""
        state.require_chat(chat_id)
        if body.page.kind != "youtube":
            raise HTTPException(422, "key moments are for a YouTube video")

        def leaf_now() -> dict[str, Any] | None:
            state.ensure_run_slot()
            leaf = state.store.leaf(chat_id)
            if leaf is not None and leaf["status"] != COMPLETED:
                raise HTTPException(409, "the last answer did not complete: retry or edit it first")
            return leaf

        leaf_now()
        content = body.page.content
        first = content.split("\n", 1)[0]
        title = (first[2:].strip() if first.startswith("# ") else "") or body.page.title.removesuffix(" - YouTube")
        try:
            made = await asyncio.to_thread(moments.key_moments, state.settings, title, content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        # Again: a message may have been sent while the model was answering. Nothing awaits
        # from here on, so the turn goes in right after the leaf read now.
        leaf = leaf_now()
        snap = leaf["after_snap"] if leaf else None
        turn = state.store.insert_turn(chat_id, "Key moments of this video",
                                       parent_turn_id=leaf["id"] if leaf else None, before_snap=snap)
        state.store.finish_turn(turn["id"], COMPLETED, after_snap=snap,
                                render=[{"kind": "text", "text": moments.answer_text(title, made)}])
        state.store.set_title(chat_id, f"Key moments: {title}"[:60], only_if_empty=True)
        state.store.mark_tainted(chat_id)   # the labels come from the page
        state.store.touch(chat_id)
        return {"chat": state.view(chat_id)}

    @api.post("/extension/fill")
    async def fill(body: FillBody) -> dict[str, Any]:
        """Suggested values for a form's fields, from the user's details. Nothing is filled here."""
        try:
            return await asyncio.to_thread(form_fill.suggest, state.settings, body.fields, body.title, state.basket)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.get("/extension/basket")
    async def basket_cards(ids: str = "") -> list[dict[str, Any]]:
        """The basket's cards as they are now: still there, changed since Fill found them, or gone."""
        out = []
        for key in [k for k in ids.split(",") if k][:40]:
            entry = state.basket.get(key)
            out.append(basket.card(state.settings, key, entry) if entry
                       else {"id": key, "available": False, "problem": "expired: run Fill again"})
        return out

    @api.get("/extension/basket/{key}")
    async def basket_file(key: str) -> Any:
        """One basket file's bytes, read now. Only ids Fill handed out, only files still in the
        allowed folders, never Atlas's own: checked again on every request."""
        entry = state.basket.get(key)
        if entry is None:
            raise HTTPException(404, "That file card has expired: run Fill again.")
        if why := basket.refusal(state.settings, entry.path):
            raise HTTPException(409, why)
        return FileResponse(entry.path, filename=entry.path.name)

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
