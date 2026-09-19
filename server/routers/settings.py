"""Settings HTTP endpoints."""
from fastapi import APIRouter, Query
from ..services.settings_service import Settings, get_public_settings, save_settings

router = APIRouter(tags=["Settings"])


@router.get("/api/settings", response_model=Settings)
async def get_settings(reveal: bool = Query(False)):
    return get_public_settings(reveal=reveal)


@router.post("/api/settings", response_model=Settings)
async def update_settings(settings: Settings, reveal: bool = Query(False)):
    save_settings(settings)
    return get_public_settings(reveal=reveal)