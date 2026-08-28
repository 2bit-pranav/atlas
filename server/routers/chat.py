from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Optional
from pydantic import BaseModel
import json
from ..services.chat_service import ChatService

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    prompt: str
    chat_id: Optional[str] = None
    thinking_budget: int = 0
    use_cloud: bool = False

@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    async def event_generator():
        async for item in ChatService.process_chat(
            prompt=req.prompt,
            chat_id=req.chat_id,
            thinking_budget=req.thinking_budget,
            use_cloud=req.use_cloud
        ):
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")