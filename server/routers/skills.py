from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..managers import skill_manager

router = APIRouter(prefix="/api/skills", tags=["Skills"])


class InstallRequest(BaseModel):
    command: str


class ScriptRequest(BaseModel):
    script: str
    args: List[str] = []


@router.get("")
async def list_skills(page: int = 1, per_page: int = 24, search: str = ""):
    result = await skill_manager.catalog(max(1, page), min(max(1, per_page), 100), search)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/local")
def list_local_skills():
    return {"skills": skill_manager.local_skills()}


@router.get("/details/{owner}/{repo}/{skill}")
async def get_remote_skill(owner: str, repo: str, skill: str):
    try:
        return await skill_manager.remote_detail(f"{owner}/{repo}/{skill}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{name}")
def get_skill(name: str):
    skill = skill_manager.get_local(name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill is not installed")
    return skill


@router.post("/install")
async def install_skill(request: InstallRequest):
    try:
        return await skill_manager.install_command(request.command)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/update-all")
async def update_all_skills():
    try:
        return await skill_manager.update_all()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{name}")
def remove_skill(name: str):
    try:
        removed = skill_manager.remove(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Skill is not installed")
    return {"status": "removed", "name": name}


@router.post("/{name}/scripts")
async def run_skill_script(name: str, request: ScriptRequest):
    try:
        return await skill_manager.run_script(name, request.script, request.args)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
