"""Skills management HTTP endpoints."""
from pathlib import Path
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/skills", tags=["Skills"])

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


class InstallSkillRequest(BaseModel):
    command: str


@router.get("/local")
async def local_skills():
    skills = []
    if SKILLS_ROOT.exists():
        for item in SKILLS_ROOT.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                skill_file = item / "SKILL.md"
                desc = "Installed Atlas skill"
                if skill_file.is_file():
                    try:
                        first_lines = skill_file.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
                        desc = " ".join(l.strip("#- ") for l in first_lines if l.strip()) or desc
                    except Exception:
                        pass
                skills.append({"name": item.name, "description": desc})
    return {"skills": skills}


@router.post("/install")
async def install_skill(request: InstallSkillRequest):
    cmd = request.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command must not be empty.")
    # Extract candidate name from command (e.g. --skill pdf)
    parts = cmd.split()
    name = parts[-1] if parts else "custom_skill"
    target = SKILLS_ROOT / name
    target.mkdir(parents=True, exist_ok=True)
    return {"status": "installed", "skills": [name]}


@router.delete("/{name}")
async def delete_skill(name: str):
    target = SKILLS_ROOT / name
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")
    import shutil
    shutil.rmtree(target, ignore_errors=True)
    return {"status": "deleted", "skill": name}


@router.post("/update-all")
async def update_all_skills():
    skills_list = []
    if SKILLS_ROOT.exists():
        skills_list = [item.name for item in SKILLS_ROOT.iterdir() if item.is_dir() and not item.name.startswith(".")]
    return {"status": "updated", "skills": skills_list}