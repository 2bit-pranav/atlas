"""GET /api/health: whether the backend is up and what is running."""

from __future__ import annotations

from typing import Any

from server.views import _run_view


def register(api: Any, state: Any) -> None:
    # ------------------------------------------------------------- health --

    @api.get("/health")
    async def health() -> dict[str, Any]:
        run = state.runs.active()
        if run is None:
            return {"status": "ok", "active_run": None}
        chat = state.store.get_chat(run.chat_id) or {}
        return {"status": "ok", "active_run": {**_run_view(run), "chat_title": chat.get("title") or ""}}
