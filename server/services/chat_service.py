import uuid
from typing import Dict, Any, AsyncGenerator
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    TextMessage,
    ThoughtEvent,
)
from autogen_agentchat.base import TaskResult
from agent.config import get_local_model, get_cloud_model
from agent.agent import create_atlas_agent

CHAT_DB: Dict[str, Dict[str, Any]] = {}

_THOUGHT_PREFIX = "<|atlas_thought|>"

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

            # Word-by-word streaming chunk from create_stream
            if isinstance(message, ModelClientStreamingChunkEvent):
                content = message.content
                if not content:
                    continue
                chunk_yielded = True
                if content.startswith(_THOUGHT_PREFIX):
                    thought_text = content[len(_THOUGHT_PREFIX):]
                    if thought_text:
                        yield {"type": "thought", "content": thought_text}
                else:
                    yield {"type": "chunk", "content": content}

            # AutoGen ThoughtEvent (emitted after inference when model_result.thought is set)
            elif isinstance(message, ThoughtEvent):
                if message.content:
                    yield {"type": "thought", "content": message.content}

            # Fallback: TaskResult when streaming did not happen
            elif isinstance(message, TaskResult) and not chunk_yielded:
                for msg in reversed(message.messages):
                    if isinstance(msg, TextMessage) and msg.source != "user":
                        yield {"type": "chunk", "content": msg.content}
                        break

        CHAT_DB[active_chat] = await atlas.save_state()