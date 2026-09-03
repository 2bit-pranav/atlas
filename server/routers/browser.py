from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..managers import browser_session_manager

router = APIRouter(prefix="/api/browser", tags=["Browser"])


class HandoffResponse(BaseModel):
    response: str


@router.get("/sessions")
def list_browser_sessions():
    return {"sessions": browser_session_manager.list_sessions()}


@router.get("/sessions/{chat_id}")
def get_browser_session(chat_id: str):
    snapshot = browser_session_manager.snapshot(chat_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Browser session not found")
    return snapshot


@router.post("/sessions/{chat_id}/handoff")
async def resolve_handoff(chat_id: str, request: HandoffResponse):
    if not await browser_session_manager.resolve_handoff(chat_id, request.response):
        raise HTTPException(status_code=404, detail="No pending browser handoff")
    return {"status": "resuming", "chat_id": chat_id}








@router.delete("/sessions/{chat_id}")
async def close_browser_session(chat_id: str):
    if not await browser_session_manager.close(chat_id):
        raise HTTPException(status_code=404, detail="Browser session not found")
    return {"status": "closed", "chat_id": chat_id}
