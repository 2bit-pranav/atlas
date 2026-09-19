"""Core chat-turn orchestration and server-sent event translation."""
import asyncio
import logging
from typing import Any, AsyncGenerator, Optional
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    TextMessage,
    ThoughtEvent,
    ToolCallRequestEvent,
)
from agent.config import get_cloud_model, get_local_model
from agent.runtime import create_runtime_agent
from agent.tools.sandbox import set_active_workspace
from ..stores import cancellation_registry, clear_emit_fn, session_store, set_emit_fn

logger = logging.getLogger(__name__)
_THOUGHT_PREFIX = "<|agent_thought|>"


def _tool_label(name: str) -> str:
    labels = {
        "search_web": "Searching the web...",
        "read_url_content": "Reading web source...",
        "run_python_code": "Running Python script in sandbox...",
        "run_command": "Running command in sandbox...",
        "view_file": "Reading file...",
        "create_file": "Creating file...",
        "edit_file": "Editing file...",
        "list_directory": "Inspecting directory...",
        "ask_question": "Waiting for user response...",
        "finish": "Finalizing task...",
    }
    return labels.get(name, f"Executing {name}...")


class ChatService:
    @staticmethod
    async def process_chat(
        *,
        chat_id: str,
        prompt: str,
        user_message_id: str,
        assistant_message_id: str,
        thinking_budget: int = 0,
        use_cloud: bool = False,
        attachments: Optional[list[dict[str, str]]] = None,
        temperature: Optional[float] = None,
        presence_penalty: float = 0.0,
        skip_user_add: bool = False,
    ) -> AsyncGenerator[dict[str, Any], None]:
        session_store.create_session(chat_id)
        session = session_store.get_session(chat_id)
        assert session is not None
        clean_prompt = prompt.strip()

        if session["title"] == "New Chat" and clean_prompt:
            first_line = clean_prompt.splitlines()[0]
            session_store.set_title(
                chat_id, first_line[:35] + ("..." if len(first_line) > 35 else "")
            )

        if not skip_user_add:
            session_store.add_message(
                chat_id,
                "user",
                clean_prompt,
                message_id=user_message_id,
                attachments=attachments,
                status="completed",
            )

        set_active_workspace(session_store.workspace_for(chat_id))
        token = cancellation_registry.create(chat_id)
        yield {"type": "meta", "chat_id": chat_id}
        yield {"type": "status", "status": "running"}

        content, thought, did_stream, stopped = "", "", False, False
        atlas = None
        task = clean_prompt
        if attachments:
            files = "\n".join(
                f"- {item['name']}: {item['path']}" for item in attachments
            )
            task = f"{clean_prompt}\n\nAttached files are available in the session workspace:\n{files}".strip()

        emitted_events: list[dict] = []

        async def _emit_to_stream(event: dict) -> None:
            emitted_events.append(event)

        set_emit_fn(_emit_to_stream)

        try:
            model_client = (
                get_cloud_model(temperature or 0.2)
                if use_cloud
                else get_local_model(
                    thinking_budget=thinking_budget,
                    temperature=temperature,
                    presence_penalty=presence_penalty,
                    chat_id=chat_id,
                )
            )
            atlas = create_runtime_agent(model_client)
            if previous_state := session_store.get_agent_state(chat_id):
                await atlas.load_state(previous_state)

            async for message in atlas.run_stream(task=task, cancellation_token=token):
                while emitted_events:
                    yield emitted_events.pop(0)

                if isinstance(message, ToolCallRequestEvent):
                    for call in message.content:
                        yield {
                            "type": "status",
                            "status": "running",
                            "label": _tool_label(call.name),
                        }
                elif isinstance(message, ModelClientStreamingChunkEvent):
                    if not message.content:
                        continue
                    did_stream = True
                    if message.content.startswith(_THOUGHT_PREFIX):
                        piece = message.content[len(_THOUGHT_PREFIX):]
                        thought += piece
                        if piece:
                            yield {"type": "thought", "content": piece}
                    else:
                        content += message.content
                        yield {"type": "chunk", "content": message.content}
                elif isinstance(message, ThoughtEvent) and message.content:
                    if not thought:
                        thought += message.content
                        yield {"type": "thought", "content": message.content}
                elif isinstance(message, TaskResult) and not did_stream:
                    for item in reversed(message.messages):
                        if isinstance(item, TextMessage) and item.source != "user":
                            content += item.content
                            yield {"type": "chunk", "content": item.content}
                            break

            stopped = token.is_cancelled()

        except BaseException as exc:
            stopped = token.is_cancelled() or isinstance(exc, (asyncio.CancelledError, GeneratorExit))
            if not stopped:
                yield {"type": "error", "detail": str(exc)}
                content = content or f"Unable to complete this turn: {exc}"
                yield {"type": "chunk", "content": content}
        finally:
            clear_emit_fn()
            cancellation_registry.remove(chat_id, token)

            final_status = "cancelled" if stopped else ("error" if not content and not stopped else "completed")
            session_store.add_message(
                chat_id,
                "assistant",
                content=content,
                message_id=assistant_message_id,
                thought=thought or None,
                status=final_status,
            )

            if not stopped and atlas is not None:
                session_store.set_agent_state(chat_id, await atlas.save_state())

            try:
                if stopped:
                    yield {"type": "status", "status": "stopped", "label": "Stopped"}
                else:
                    yield {"type": "status", "status": "completed", "label": "Completed"}
            except (GeneratorExit, RuntimeError):
                pass