from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig, chain
from langserve import add_routes
from pydantic import BaseModel, Field

from agent import get_atlas_graph
from browser.manager import BrowserManager


# PATHS / STORAGE
ROOT_DIR = Path(__file__).resolve().parent.parent
SAVES_DIR = ROOT_DIR / "saves"
CHECKPOINTS_DIR = ROOT_DIR / "core/checkpoints"

PROFILES_DIR = SAVES_DIR / "profiles"
DB_PATH = CHECKPOINTS_DIR / "atlas_memory.db"

PROFILES_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


# MODELS
class AtlasInput(BaseModel):
    message: str = Field(..., description="The message you want to send to Atlas.")


class ProfileCreate(BaseModel):
    name: str


# HELPERS
def sanitize_filename(name: str) -> str:
    """
    Converts:
    'Work Profile!!' -> 'work_profile'
    Because users type things like raccoons on keyboards.
    """
    clean = name.strip().lower()
    clean = re.sub(r"\s+", "_", clean)
    clean = re.sub(r"[^a-z0-9_]", "", clean)
    return clean or "profile"


def _normalize_inputs(inputs: AtlasInput | dict[str, Any]) -> AtlasInput:
    if isinstance(inputs, AtlasInput):
        return inputs

    if isinstance(inputs, dict):
        payload = inputs.get("input", inputs)
        if isinstance(payload, dict):
            return AtlasInput(**payload)

    raise TypeError("Unsupported input payload for Atlas")


def prepare_state(inputs: AtlasInput | dict[str, Any]) -> dict[str, Any]:
    parsed = _normalize_inputs(inputs)

    return {
        "messages": [
            HumanMessage(content=parsed.message)
        ]
    }


SESSION_ID = str(uuid.uuid4())


# APP LIFECYCLE
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield

    # shutdown
    if BrowserManager._instance is not None:
        print("Saving browser state and closing Playwright...")
        await BrowserManager._instance.close()


app = FastAPI(
    title="Atlas Browser Agent",
    version="0.1.0",
    description="Local LangGraph backend for Atlas.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# MAIN STREAM CHAIN
@chain
async def atlas_api(inputs: AtlasInput, config: RunnableConfig):
    state = prepare_state(inputs)
    atlas_graph = await get_atlas_graph()

    config["configurable"] = {
        "thread_id": SESSION_ID
    }

    async for event in atlas_graph.astream(
        state,
        config=config,
        stream_mode="values"
    ):
        clean_messages = []

        for msg in event.get("messages", []):
            content = msg.content

            if isinstance(content, list):
                content = "".join(
                    block.get("text", "")
                    if isinstance(block, dict)
                    else str(block)
                    for block in content
                )

            clean_messages.append({
                "type": msg.type,
                "content": content,
                "id": getattr(msg, "id", "")
            })

        yield {
            "messages": clean_messages,
            "logs": event.get("logs", [])
        }


atlas_api = atlas_api.with_types(input_type=AtlasInput)

add_routes(app, atlas_api, path="/atlas")


# CHAT HISTORY
@app.get("/atlas/history")
async def get_chat_history():
    """
    Returns unique sessions for sidebar history.
    """

    if not DB_PATH.exists():
        return {"history": []}

    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT thread_id, MAX(checkpoint_id) AS last_updated
                FROM checkpoints
                GROUP BY thread_id
                ORDER BY last_updated DESC
            """)

            rows = await cursor.fetchall()

            history = [
                {
                    "id": row["thread_id"],
                    "name": f"Session {row['thread_id'][:6]}",
                    "updatedAt": row["last_updated"]
                }
                for row in rows
            ]

            return {"history": history}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# PROFILES
@app.get("/atlas/profiles")
async def get_profiles():
    """
    Returns all saved browser profiles.
    """

    profiles = []

    for file in PROFILES_DIR.glob("*.json"):
        profiles.append({
            "id": file.stem,
            "name": file.stem.replace("_", " ").title(),
            "storedData": "Saved logins, cookies, preferences"
        })

    return {"profiles": profiles}


@app.post("/atlas/profiles")
async def create_profile(request: ProfileCreate):
    """
    Creates empty Playwright storage state profile.
    """

    safe_name = sanitize_filename(request.name)
    file_path = PROFILES_DIR / f"{safe_name}.json"

    if file_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Profile already exists."
        )

    empty_state = {
        "cookies": [],
        "origins": []
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(empty_state, f, indent=4)

    return {
        "message": f"Profile '{safe_name}' created successfully.",
        "id": safe_name
    }


# DEV ENTRYPOINT
if __name__ == "__main__":

    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsProactorEventLoopPolicy()
        )

    print("Booting Atlas Dev Server... because rest is forbidden.")

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        loop="asyncio",
        reload=False
    )