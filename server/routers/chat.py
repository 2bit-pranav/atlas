"""Chat, stop, edit, retry, permission, and answer HTTP endpoints."""
import json
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ..services.chat_service import ChatService
from ..stores import cancellation_registry, session_store, resolve_permission, resolve_user_input

router = APIRouter(prefix="/api/chat", tags=["Chat"])

class EditRequest(BaseModel):
    new_prompt: str
    use_cloud: bool = False
    thinking_budget: int = 0


class RetryRequest(BaseModel):
    use_cloud: bool = False
    thinking_budget: int = 0


def _stream(generator):
    async def events():
        async for item in generator:
            yield f"data: {json.dumps(item)}\n\n"
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _save_uploads(
    chat_id: str, uploads: list[UploadFile]
) -> list[dict[str, str]]:
    directory = session_store.workspace_for(chat_id) / "uploads"
    directory.mkdir(exist_ok=True)
    payload: list[dict[str, str]] = []
    for upload in uploads:
        if not upload.filename:
            continue
        name = Path(upload.filename).name
        destination = directory / name
        destination.write_bytes(await upload.read())
        payload.append({"name": name, "path": str(destination)})
    return payload


@router.post("")
async def chat_endpoint(
    prompt: str = Form(...),
    chat_id: Optional[str] = Form(None),
    user_message_id: Optional[str] = Form(None),
    assistant_message_id: Optional[str] = Form(None),
    thinking_budget: int = Form(0),
    use_cloud: bool = Form(False),
    attachments: list[UploadFile] = File(default_factory=list),
    files: list[UploadFile] = File(default_factory=list),
):
    active_chat_id = (
        chat_id.strip() if chat_id and chat_id.strip() else str(uuid.uuid4())
    )
    try:
        session_store.create_session(active_chat_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = await _save_uploads(active_chat_id, [*attachments, *files])
    return _stream(
        ChatService.process_chat(
            chat_id=active_chat_id,
            prompt=prompt,
            user_message_id=user_message_id or str(uuid.uuid4()),
            assistant_message_id=assistant_message_id or str(uuid.uuid4()),
            thinking_budget=thinking_budget,
            use_cloud=use_cloud,
            attachments=saved,
            skip_user_add=False,
        )
    )


@router.post("/{chat_id}/stop")
async def stop_chat(chat_id: str):
    return {
        "status": (
            "stopping" if cancellation_registry.cancel(chat_id) else "not_running"
        ),
        "chat_id": chat_id,
    }


@router.post("/{chat_id}/messages/{message_id}/edit")
async def edit_message(chat_id: str, message_id: str, request: EditRequest):
    session = session_store.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    original_msg = next((m for m in session.get("messages", []) if m.get("id") == message_id), None)
    attachments = original_msg.get("attachments", []) if original_msg else []

    if not session_store.truncate_to_message(chat_id, message_id, include=False, clear_state=True):
        raise HTTPException(status_code=404, detail="Message not found")

    return _stream(
        ChatService.process_chat(
            chat_id=chat_id,
            prompt=request.new_prompt,
            user_message_id=message_id,
            assistant_message_id=str(uuid.uuid4()),
            thinking_budget=request.thinking_budget,
            use_cloud=request.use_cloud,
            attachments=attachments,
            skip_user_add=False,
        )
    )


@router.post("/{chat_id}/messages/{message_id}/retry")
async def retry_message(chat_id: str, message_id: str, request: RetryRequest):
    session = session_store.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = session.get("messages", [])
    target_index = next((i for i, m in enumerate(messages) if m.get("id") == message_id), -1)

    if target_index < 1 or messages[target_index].get("role") != "assistant":
        raise HTTPException(status_code=400, detail="Retry requires an existing assistant message")

    if messages[target_index].get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot retry cancelled messages. Edit prompt instead.")

    user_msg = messages[target_index - 1]

    # Keep the user prompt, drop only the assistant message, preserve prior agent context
    session_store.truncate_to_message(chat_id, user_msg["id"], include=True, clear_state=True)

    return _stream(
        ChatService.process_chat(
            chat_id=chat_id,
            prompt=user_msg.get("content", ""),
            user_message_id=user_msg["id"],
            assistant_message_id=message_id,
            thinking_budget=request.thinking_budget,
            use_cloud=request.use_cloud,
            attachments=user_msg.get("attachments", []),
            skip_user_add=True,
        )
    )


class PermissionResponse(BaseModel):
    request_id: str
    allow: bool


@router.post("/{chat_id}/permission")
async def resolve_permission_endpoint(chat_id: str, body: PermissionResponse):
    resolved = resolve_permission(body.request_id, body.allow)
    return {"resolved": resolved, "request_id": body.request_id, "allow": body.allow}


class AnswerResponse(BaseModel):
    question_id: str
    answer: str


@router.post("/{chat_id}/answer")
async def resolve_answer_endpoint(chat_id: str, body: AnswerResponse):
    resolved = resolve_user_input(body.question_id, body.answer)
    return {"resolved": resolved, "question_id": body.question_id}