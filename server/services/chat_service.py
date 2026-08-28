import uuid
from typing import Dict, Any, AsyncGenerator
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage
from autogen_agentchat.base import TaskResult
from agent.config import get_local_model, get_cloud_model
from agent.agent import create_atlas_agent

CHAT_DB: Dict[str, Dict[str, Any]] = {}

class ChatService:

    @staticmethod
    async def process_chat(
        prompt: str,
        chat_id: str = None,
        thinking_budget: int = 0,
        use_cloud: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:

        active_chat = chat_id or str(uuid.uuid4())

        if not use_cloud:
            model_client = get_local_model(thinking_budget=thinking_budget)
        else:
            model_client = get_cloud_model()

        atlas = create_atlas_agent(model_client=model_client)

        if active_chat in CHAT_DB:
            await atlas.load_state(CHAT_DB[active_chat])

        yield {"type": "meta", "chat_id": active_chat}

        chunk_yielded = False
        async for message in atlas.run_stream(task=prompt):
            if isinstance(message, ModelClientStreamingChunkEvent):
                if message.content:
                    chunk_yielded = True
                    yield {"type": "chunk", "content": message.content}

            # fallback if response not streamed
            elif isinstance(message, TaskResult) and not chunk_yielded:
                for msg in reversed(message.messages):
                    if isinstance(msg, TextMessage) and msg.source != "user":
                        yield {"type": "chunk", "content": msg.content}
                        break

        CHAT_DB[active_chat] = await atlas.save_state()