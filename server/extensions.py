"""Skills and MCP routes, under `/api` beside the rest.

Installs, uploads and registry searches touch the network or the disk, so each
runs in a worker thread: a slow GitHub download must not freeze a live answer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

from agent.core import paths
from agent.core.mcp_manager import McpError, search_registry
from agent.core.settings import write_settings
from agent.core.skill_installer import (
    delete_skill,
    install_zip,
    preview_or_install,
)
from agent.core import skill_requirements
from agent.core.skill_manager import SkillError, SkillManager


class InstallSkill(BaseModel):
    command: str
    choose: list[str] | None = None
    replace: bool = False


class Toggle(BaseModel):
    enabled: bool


class ToolMode(BaseModel):
    mode: str


class McpServerBody(BaseModel):
    name: str
    config: dict[str, Any]


def register(app: FastAPI, state: Any) -> None:
    api = APIRouter(prefix="/api")

    def skills() -> list[dict[str, Any]]:
        return SkillManager(state.settings).catalogue()

    def skill_dir():
        return paths.skills_dir(state.settings)

    def refuse(exc: Exception, code: int = 422) -> HTTPException:
        return HTTPException(code, str(exc))

    # -------------------------------------------------------------- skills --

    @api.get("/skills")
    async def list_skills() -> list[dict[str, Any]]:
        return skills()

    @api.post("/skills/install")
    async def install(body: InstallSkill) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(preview_or_install, skill_dir(), body.command,
                                             choose=body.choose, replace=body.replace)
        except SkillError as exc:
            raise refuse(exc) from exc
        except Exception as exc:  # noqa: BLE001 - network errors read fine as-is
            raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
        return {**result, "skills": skills()}

    @api.post("/skills/upload")
    async def upload(request: Request) -> dict[str, Any]:
        form = await request.form()
        file = form.get("file")
        if file is None or isinstance(file, str):
            raise HTTPException(422, "no file part")
        data = await file.read()
        try:
            result = await asyncio.to_thread(install_zip, skill_dir(), data,
                                             file.filename or "skill.zip",
                                             replace=form.get("replace") == "true")
        except SkillError as exc:
            raise refuse(exc) from exc
        return {**result, "skills": skills()}

    @api.put("/skills/{folder}")
    async def toggle_skill(folder: str, body: Toggle) -> list[dict[str, Any]]:
        import json

        on_disk = json.loads(state.settings_path.read_text(encoding="utf-8"))
        disabled = set(on_disk.setdefault("skills", {}).get("disabled") or [])
        (disabled.discard if body.enabled else disabled.add)(folder)
        on_disk["skills"]["disabled"] = sorted(disabled)
        write_settings(state.settings_path, on_disk)
        state.settings = state.settings.model_copy(
            update={"skills": state.settings.skills.model_copy(update={"disabled": sorted(disabled)})})
        return skills()

    @api.delete("/skills/{folder}")
    async def remove_skill(folder: str) -> list[dict[str, Any]]:
        try:
            delete_skill(skill_dir(), folder)
        except SkillError as exc:
            raise refuse(exc, 409) from exc
        return skills()

    @api.post("/skills/{folder}/requirements")
    async def requirements(folder: str) -> dict[str, Any]:
        match = next((s for s in skills() if s["folder"] == folder), None)
        if match is None:
            raise HTTPException(404, f"no skill {folder}")
        try:
            return await asyncio.to_thread(skill_requirements.install, Path(match["path"]), match["requirements"])
        except SkillError as exc:
            raise refuse(exc) from exc

    # ----------------------------------------------------------------- mcp --

    async def mcp_call(fn, *args) -> Any:
        try:
            return await asyncio.to_thread(fn, *args)
        except McpError as exc:
            raise refuse(exc) from exc

    @api.get("/mcp")
    async def list_mcp() -> list[dict[str, Any]]:
        return await mcp_call(state.mcp.describe)

    @api.post("/mcp")
    async def upsert_mcp(body: McpServerBody) -> list[dict[str, Any]]:
        await mcp_call(state.mcp.upsert, body.name, body.config)
        return await mcp_call(state.mcp.describe)

    @api.delete("/mcp/{name}")
    async def delete_mcp(name: str) -> list[dict[str, Any]]:
        await mcp_call(state.mcp.remove, name)
        return await mcp_call(state.mcp.describe)

    @api.put("/mcp/{name}")
    async def toggle_mcp(name: str, body: Toggle) -> list[dict[str, Any]]:
        await mcp_call(state.mcp.set_enabled, name, body.enabled)
        return await mcp_call(state.mcp.describe)

    @api.post("/mcp/{name}/reconnect")
    async def reconnect_mcp(name: str) -> list[dict[str, Any]]:
        await mcp_call(state.mcp.reconnect, name)
        return await mcp_call(state.mcp.describe)

    @api.put("/mcp/{name}/tools/{tool}")
    async def set_mcp_tool(name: str, tool: str, body: ToolMode) -> list[dict[str, Any]]:
        await mcp_call(state.mcp.set_tool, name, tool, body.mode)
        return await mcp_call(state.mcp.describe)

    @api.get("/mcp/registry")
    async def registry(q: str = "") -> list[dict[str, Any]]:
        try:
            return await asyncio.to_thread(search_registry, q)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"the MCP registry could not be reached: {exc}") from exc

    # No GET route matches `/mcp/{name}`, so `/mcp/registry` is never shadowed.
    app.include_router(api)
