"""A chat's files: uploads, PDFs imported by link, the workspace, downloads."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from agent.config import paths
from server.schemas import (
    ImportFile,
)
from server.services.workspace import _scan
from skills._shared import LinkError, save_link  # the one document-link resolver


def register(api: Any, state: Any) -> None:
    # --------------------------------------------------------------- files --

    @api.post("/chats/{chat_id}/files")
    async def upload(chat_id: str, request: Request) -> dict[str, Any]:
        state.require_chat(chat_id)
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None or isinstance(upload_file, str):
            raise HTTPException(422, "no file part")
        name = Path(upload_file.filename or "upload.bin").name
        target = state.chat_dir(chat_id) / name

        # Nothing is parsed at upload: the file is saved and the model reads it
        # on demand through a skill. Copying is still blocking I/O, so it runs
        # off the event loop and cannot freeze an active run's stream.
        def _save() -> None:
            with target.open("wb") as fh:
                shutil.copyfileobj(upload_file.file, fh)

        await asyncio.to_thread(_save)
        return {"name": name, "path": str(target), "size": target.stat().st_size,
                "type": mimetypes.guess_type(name)[0] or "application/octet-stream"}

    @api.post("/chats/{chat_id}/files/import")
    async def import_file(chat_id: str, body: ImportFile) -> dict[str, Any]:
        """A PDF the extension's tab shows, as an attachment.

        The browser's PDF viewer runs no content script, so the page tools
        cannot read it; the file goes to the workspace for the pdf skill. A
        `file://` PDF is copied from disk (so no "allow access to file URLs"
        switch is needed); a web one is downloaded, for when the extension could
        not fetch it itself.
        """
        state.require_chat(chat_id)
        try:
            target, _ = await asyncio.to_thread(save_link, body.url, ".pdf", b"%PDF", "PDF",
                                                state.chat_dir(chat_id), copy_local=True)
        except LinkError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"name": target.name, "path": str(target), "size": target.stat().st_size,
                "type": "application/pdf"}

    def workspace_file(chat_id: str, name: str) -> Path:
        state.require_chat(chat_id)
        root = paths.chat_dir(state.settings, chat_id).resolve()
        target = (root / name).resolve()
        if root not in target.parents:
            raise HTTPException(400, "path escapes the chat directory")
        if not target.is_file():
            raise HTTPException(404, "no such file")
        return target

    @api.delete("/chats/{chat_id}/files/{name:path}")
    async def remove_upload(chat_id: str, name: str) -> dict[str, Any]:
        """Remove an upload the user took off a message before sending it.

        Refused for a file any sent message used: that message's history, and
        any document made from it, still point at it.
        """
        target = workspace_file(chat_id, name)
        for row in state.store.export_rows(chat_id)["turns"]:
            if any(f.get("name") == target.name for f in json.loads(row["files_json"] or "[]")):
                raise HTTPException(409, f"{target.name} was sent with a message and is kept")
        target.unlink()
        return {"deleted": name}

    @api.get("/chats/{chat_id}/workspace")
    async def workspace(chat_id: str) -> list[dict[str, Any]]:
        """Every file in the chat's workspace, newest first. Outlives any edit."""
        state.require_chat(chat_id)
        root = state.chat_dir(chat_id)
        entries = [{"name": name, "size": size, "path": str(root / name),
                    "modified": mtime // 1_000_000,
                    "type": mimetypes.guess_type(name)[0] or "application/octet-stream"}
                   for name, (size, mtime) in _scan(root).items()]
        return sorted(entries, key=lambda e: e["modified"], reverse=True)

    @api.get("/chats/{chat_id}/files/{name:path}")
    async def download(chat_id: str, name: str, download: bool = False) -> FileResponse:
        """A workspace file, downloaded. Raster images are shown inline (attachment
        thumbnails); nothing else is, so a file the agent wrote (HTML, SVG) never
        runs as a page on Atlas's own origin."""
        target = workspace_file(chat_id, name)
        kind = mimetypes.guess_type(target.name)[0] or ""
        if download or not kind.startswith("image/") or kind == "image/svg+xml":
            return FileResponse(target, filename=target.name, headers={"X-Content-Type-Options": "nosniff"})
        return FileResponse(target, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
