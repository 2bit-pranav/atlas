"""Settings, models, and restarting the servers from the UI."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent.config import paths
from agent.config.settings import (
    TIERS,
    SettingsError,
    changed_restart_keys,
    flatten,
    parse_settings,
    set_path,
    write_settings,
)
from agent.integrations.skills.catalog import SkillManager
from agent.model import server as llama
from agent.runtime.memory import MemoryManager
from agent.tools.manager import ToolManager
from agent.tools.web import read_key, write_key
from server.services.settings_service import _launched_restart_values, _live_settings


def register(api: Any, state: Any) -> Any:
    # ------------------------------------------------------------ settings --

    def settings_view() -> dict[str, Any]:
        on_disk = json.loads(state.settings_path.read_text(encoding="utf-8"))
        return {
            "values": flatten(parse_settings(on_disk).model_dump(mode="json")),
            "tiers": {k: t.value for k, t in TIERS.items()},
            "pending_restart": changed_restart_keys(on_disk, _launched_restart_values(state)),
            "tools": ToolManager(state.settings).describe(),
            "memory": MemoryManager(state.settings).describe(),
            "skills": SkillManager(state.settings).catalogue(),
            "mcp": state.mcp.describe(),
            "paths": {"root": str(paths.ROOT), "data": str(paths.data_dir(state.settings))},
            "modalities": state.modalities(),
            # Whether a key is set, never the key: this view is open to the extension too.
            "web": {"exa_key_set": bool(read_key(paths.data_dir(state.settings)))},
        }

    @api.put("/secrets/exa")
    async def put_exa_key(body: dict[str, Any]) -> dict[str, Any]:
        """Set (or, empty, clear) the Exa key. The web UI's alone (not in EXTENSION_ROUTES);
        kept in the data folder, which the agent can never read."""
        key = body.get("key")
        if not isinstance(key, str) or len(key) > 200 or any(c.isspace() for c in key.strip()):
            raise HTTPException(422, "the key is one line of letters, digits and dashes")
        write_key(paths.data_dir(state.settings), key)
        return {"exa_key_set": bool(key.strip())}

    @api.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return settings_view()

    @api.put("/settings")
    async def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        """Write any key. LIVE keys apply on the next turn; RESTART keys are
        saved to settings.json and take effect at the next `atlas start`."""
        unknown = sorted(k for k in patch if k not in TIERS)
        if unknown:
            raise HTTPException(422, f"unknown setting(s): {unknown}")
        on_disk = json.loads(state.settings_path.read_text(encoding="utf-8"))
        for dotted, value in patch.items():
            set_path(on_disk, dotted, value)
        try:
            write_settings(state.settings_path, on_disk)
        except SettingsError as exc:
            raise HTTPException(422, str(exc)) from exc
        state.settings = _live_settings(on_disk, state.boot)
        # Servers whose arguments hold {atlas:folders} reconnect with the new list.
        await asyncio.to_thread(state.mcp.set_settings, state.settings)
        return settings_view()

    # ------------------------------------------------------------- models --

    @api.get("/models")
    async def list_models() -> dict[str, Any]:
        """The models in the models folder, for the Settings picker."""
        found = await asyncio.to_thread(llama.discover, paths.models_dir(state.settings))
        return {"models": [m.describe() for m in found], "loaded": state.boot.model.name,
                "selected": state.settings.model.name}

    # ------------------------------------------------------------ restart --

    @api.get("/restart")
    async def restart_status() -> dict[str, Any]:
        """How the last restart went: restarting, ready or failed (with why)."""
        status = os.environ.get("ATLAS_RESTART_STATUS")
        available = bool(os.environ.get("ATLAS_RESTART_REQUEST"))
        try:
            data = json.loads(Path(status).read_text(encoding="utf-8")) if status else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        return {"available": available, **data}

    @api.post("/restart")
    async def restart() -> dict[str, Any]:
        """Ask `atlas start` to restart llama-server and this backend.

        The CLI watches for the request file; this process is replaced, so the
        UI polls GET /restart until it answers again.
        """
        request = os.environ.get("ATLAS_RESTART_REQUEST")
        if not request:
            raise HTTPException(409, "Atlas was not started with `atlas start`, so it cannot restart itself. "
                                     "Stop it and start it again by hand.")
        if state.runs.active():
            raise HTTPException(409, "An answer is being written. Stop it or wait, then restart.")
        Path(request).write_text(str(int(time.time() * 1000)), encoding="utf-8")
        return {"ok": True}

    return settings_view
