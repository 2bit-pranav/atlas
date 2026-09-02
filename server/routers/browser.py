from fastapi import APIRouter, HTTPException
from ..managers import browser_session_manager

router = APIRouter(prefix="/api/browser", tags=["Browser"])


@router.get("/sessions")
def list_browser_sessions():
    return {"sessions": browser_session_manager.list_sessions()}


@router.get("/sessions/{chat_id}")
def get_browser_session(chat_id: str):
    snapshot = browser_session_manager.snapshot(chat_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Browser session not found")
    return snapshot








@router.delete("/sessions/{chat_id}")
async def close_browser_session(chat_id: str):
    if not await browser_session_manager.close(chat_id):
        raise HTTPException(status_code=404, detail="Browser session not found")
    return {"status": "closed", "chat_id": chat_id}
