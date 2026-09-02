import json
import shutil
import uuid
from pathlib import Path
from typing import Optional, List, Dict
from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

from ..services.chat_service import ChatService
from ..managers import chat_session_manager

router = APIRouter(prefix="/api", tags=["Chat"])
UPLOADS_BASE_DIR = Path(__file__).resolve().parent.parent / "uploads"


@router.post("/chat")
async def chat_endpoint(
    prompt: str = Form(...),
    chat_id: Optional[str] = Form(None),
    thinking_budget: int = Form(0),
    use_cloud: bool = Form(False),
    attachments: list[UploadFile] = File(default_factory=list),
):
    active_chat_id = chat_id if (chat_id and chat_id.strip()) else str(uuid.uuid4())
    attachment_payloads: List[Dict[str, str]] = []

    if attachments:
        chat_upload_dir = UPLOADS_BASE_DIR / active_chat_id
        chat_upload_dir.mkdir(parents=True, exist_ok=True)

        for file in attachments:
            if not file.filename:
                continue

            orig_filename = Path(file.filename).name
            file_path = chat_upload_dir / orig_filename
            content = await file.read()
            file_path.write_bytes(content)

            attachment_payloads.append({
                "name": orig_filename,
                "path": str(file_path),
            })

    async def event_generator():
        async for item in ChatService.process_chat(
            chat_id=active_chat_id,
            prompt=prompt,
            attachments=attachment_payloads,
            thinking_budget=thinking_budget,
            use_cloud=use_cloud,
        ):
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions")
async def get_sessions():
    return chat_session_manager.get_all_sessions()


@router.get("/sessions/{chat_id}")
async def get_session(chat_id: str):
    session = chat_session_manager.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{chat_id}")
async def delete_session(chat_id: str):
    # Delete session from manager
    if not chat_session_manager.delete_session(chat_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Clean up uploads directory
    uploads_dir = UPLOADS_BASE_DIR / chat_id
    if uploads_dir.exists():
        shutil.rmtree(uploads_dir, ignore_errors=True)

    return {"status": "success", "chat_id": chat_id}