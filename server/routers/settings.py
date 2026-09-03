from fastapi import APIRouter
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import json

router = APIRouter()

# settings.json lives at the project root (two levels above server/routers/)
SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"


class Settings(BaseModel):
    # Inference Engine
    local_model_url: Optional[str] = "http://127.0.0.1:8000/v1"
    local_model_name: Optional[str] = "gemma-4-E2B_q4_0-it.gguf"
    cloud_provider: Optional[str] = "google"
    cloud_model_name: Optional[str] = "gemini-3.5-flash-lite"
    cloud_api_key: Optional[str] = ""
    # Web Research
    exa_api_key: Optional[str] = ""
    web_search_enabled: bool = True
    web_search_max_results: int = 5
    # Browser Automation
    browser_headless: bool = False
    browser_width: int = 1280
    browser_height: int = 720
    browser_max_steps: int = 10
    browser_max_failures: int = 2
    browser_enable_planning: bool = True
    browser_wait_strategy: str = "smart"
    browser_page_load_timeout: int = 30
    browser_use_vision: bool = False
    # Agent Behavior
    agent_max_tool_iterations: int = 5
    agent_reflect_on_tool_use: bool = True
    agent_stream_thoughts: bool = True
    agent_thinking_budget: str = "off"
    # Session & Memory
    session_persist: bool = True
    session_max_count: int = 50


def _load() -> Settings:
    if SETTINGS_PATH.is_file():
        try:
            data = json.loads(SETTINGS_PATH.read_text("utf-8"))
            return Settings.model_validate(data)
        except Exception:
            pass
    return Settings()


def _save(settings: Settings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(settings.model_dump_json(indent=2), "utf-8")


@router.get("/settings", response_model=Settings, tags=["Settings"])
async def get_settings():
    return _load()


@router.post("/settings", response_model=Settings, tags=["Settings"])
async def update_settings(settings: Settings):
    _save(settings)
    return settings
