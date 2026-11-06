"""Chats: list, create, read, rename, delete, export and import."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from fastapi import HTTPException

from agent.config import paths
from agent.ingest.store import store_for
from agent.store.snapshots import SessionManager
from server.schemas import (
    CreateChat,
    RenameChat,
)


def register(api: Any, state: Any) -> None:

    @api.get("/chats")
    async def list_chats() -> list[dict[str, Any]]:
        return state.store.list_chats()

    @api.get("/outputs")
    async def recent_outputs() -> list[dict[str, Any]]:
        """Files runs made lately, across chats, for the home page. Still on disk only.
        The web UI's alone: not in the extension's routes."""
        files = state.store.recent_files(limit=12)
        return [f for f in files if (paths.chat_dir(state.settings, f["chat_id"]) / f["name"]).is_file()][:6]

    @api.post("/chats")
    async def create_chat(body: CreateChat | None = None) -> dict[str, Any]:
        if body is None:
            return state.store.create_chat("")
        source = body.source if body.source in ("web", "extension") else "web"
        return state.store.create_chat(body.title or "", source=source, page_url=body.page_url[:2000],
                                       page_title=body.page_title[:300])

    @api.get("/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        return state.view(chat_id)

    @api.patch("/chats/{chat_id}")
    async def rename_chat(chat_id: str, body: RenameChat) -> dict[str, Any]:
        state.require_chat(chat_id)
        state.store.set_title(chat_id, body.title.strip()[:200])
        return state.store.get_chat(chat_id)  # type: ignore[return-value]

    @api.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        state.require_chat(chat_id)
        if state.runs.active_for_chat(chat_id):
            raise HTTPException(409, "cannot delete a chat with an active run")
        state.store.delete_chat(chat_id)
        state.chat_grants.pop(chat_id, None)
        await SessionManager(state.settings, chat_id).delete_all()
        shutil.rmtree(paths.chat_dir(state.settings, chat_id), ignore_errors=True)
        # Its parsed documents too, unless another chat has the same file.
        await asyncio.to_thread(store_for(paths.data_dir(state.settings)).forget_chat, chat_id)
        return {"deleted": chat_id}

    @api.get("/chats/{chat_id}/export")
    async def export_chat(chat_id: str) -> dict[str, Any]:
        """Everything needed to restore the chat elsewhere, version tree and
        Strands snapshots included, so an imported chat can be continued."""
        state.require_chat(chat_id)
        rows = state.store.export_rows(chat_id)
        snaps = await SessionManager(state.settings, chat_id).read_snapshots(
            t["after_snap"] for t in rows["turns"])
        return {"format": "atlas-chat", "version": 1, **rows, "snapshots": snaps}

    @api.post("/chats/import")
    async def import_chat(body: dict[str, Any]) -> dict[str, Any]:
        if body.get("format") != "atlas-chat" or not isinstance(body.get("turns"), list):
            raise HTTPException(422, "not an Atlas chat export")
        chat_id = state.store.import_rows(body.get("chat") or {}, body["turns"])
        await SessionManager(state.settings, chat_id).write_snapshots(body.get("snapshots") or {})
        return state.store.get_chat(chat_id)  # type: ignore[return-value]
