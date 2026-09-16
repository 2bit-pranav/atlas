from fastapi import APIRouter, Query

from ..services.settings_service import Settings, get_public_settings, save_settings

router = APIRouter()


@router.get("/settings", response_model=Settings, tags=["Settings"])
async def get_settings(reveal: bool = Query(False)):
    return get_public_settings(reveal=reveal)


@router.post("/settings", response_model=Settings, tags=["Settings"])
async def update_settings(settings: Settings, reveal: bool = Query(False)):
    save_settings(settings)
    return get_public_settings(reveal=reveal)
