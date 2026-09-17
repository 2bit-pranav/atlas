from fastapi import APIRouter

router = APIRouter(prefix="/api/browser", tags=["Browser"])


@router.get("/sessions")
async def browser_sessions():
    return {"sessions": []}
