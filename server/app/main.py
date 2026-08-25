import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ensure project root is in sys path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent.agent import AtlasAgent

app = FastAPI()

# enable CORS for frontend client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

atlas_agent = AtlasAgent()

class ChatRequest(BaseModel):
    prompt: str

@app.get("/")
async def root():
    return {"message": "atlas says hi"}

# stream model response to client
@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.prompt or not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    return StreamingResponse(
        atlas_agent.chat(request.prompt),
        media_type="text/plain"
    )

# reset agent message history
@app.post("/reset")
async def reset_endpoint():
    await atlas_agent.reset()
    return {"status": "ok", "message": "History reset successfully"}