"""Agent memory facts storage and retrieval router."""
import json
import logging
import shutil
from pathlib import Path
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["Memory"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_DIR = PROJECT_ROOT / ".storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_PATH = STORAGE_DIR / "memory.json"


DEFAULT_FACTS = [
    {
        "id": "fact-1",
        "text": "User prefers train travel over flights for domestic trips",
        "category": "Preferences",
        "created_at": "2026-09-01",
    },
    {
        "id": "fact-2",
        "text": "Target budget range for hardware/laptop recommendations is under $1500",
        "category": "Budget",
        "created_at": "2026-09-02",
    },
    {
        "id": "fact-3",
        "text": "Default UI color theme preference is Dark Mode",
        "category": "UI Settings",
        "created_at": "2026-09-03",
    },
]


class MemoryFact(BaseModel):
    id: str
    text: str
    category: str
    created_at: str


class MemoryPayload(BaseModel):
    facts: List[MemoryFact] = Field(default_factory=list)


def _read_facts() -> List[dict]:
    if MEMORY_PATH.is_file():
        try:
            content = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(content, list):
                return content
        except Exception as exc:
            logger.error("Error reading memory.json: %s", exc)
    
    # Initialize with default facts if not present
    try:
        MEMORY_PATH.write_text(json.dumps(DEFAULT_FACTS, indent=2), encoding="utf-8")
    except Exception:
        pass
    return DEFAULT_FACTS


@router.get("")
async def get_memory():
    return {"facts": _read_facts()}


@router.post("")
async def save_memory(payload: MemoryPayload):
    try:
        data = [fact.model_dump() for fact in payload.facts]
        MEMORY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"facts": data}
    except Exception as exc:
        logger.error("Error writing memory.json: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to write memory file.")