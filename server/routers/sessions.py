from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..stores import session_store

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])


class UpdateTitleRequest(BaseModel):
    title: str


@router.get("")
async def list_sessions():
    return session_store.get_all_sessions()


@router.get("/{chat_id}")
async def get_session(chat_id: str):
    session = session_store.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{chat_id}/title")
async def update_session_title(chat_id: str, request: UpdateTitleRequest):
    if not session_store.set_title(chat_id, request.title):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "updated", "chat_id": chat_id, "title": request.title}


@router.delete("/{chat_id}")
async def delete_session(chat_id: str):
    deleted = session_store.delete_session(chat_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "chat_id": chat_id}
