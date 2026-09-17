"""Dual async interaction gates: permission (bool) and clarification (str)."""

import asyncio
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Coroutine

# Emitter context: set per-request to the SSE emit callable
_emit_var: ContextVar[Callable[[dict], Coroutine[Any, Any, None]] | None] = ContextVar(
    "atlas_emit", default=None
)

# Pending futures keyed by request_id / question_id
_perm_futures: dict[str, asyncio.Future[bool]] = {}
_input_futures: dict[str, asyncio.Future[str]] = {}


def set_emit_fn(emit_fn: Callable[[dict], Coroutine[Any, Any, None]]) -> None:
    """Bind the SSE emit callable to the current async context."""
    _emit_var.set(emit_fn)


def clear_emit_fn() -> None:
    """Unbind the SSE emit callable."""
    _emit_var.set(None)


async def _emit(event: dict) -> None:
    fn = _emit_var.get()
    if fn is not None:
        await fn(event)


async def request_permission(tool_name: str, target: str, details: dict | None = None) -> bool:
    """Gate: emit a permission_request SSE event and await a bool resolution."""
    request_id = f"perm_{uuid.uuid4().hex[:8]}"
    loop = asyncio.get_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    _perm_futures[request_id] = future
    await _emit(
        {
            "type": "permission_request",
            "request_id": request_id,
            "tool": tool_name,
            "target": target,
            "details": details or {},
        }
    )
    try:
        return await future
    finally:
        _perm_futures.pop(request_id, None)


def resolve_permission(request_id: str, allow: bool) -> bool:
    """Resolve the boolean gate for a pending permission request."""
    future = _perm_futures.get(request_id)
    if future is None or future.done():
        return False
    future.set_result(allow)
    return True


async def request_user_input(question: str) -> str:
    """Gate: emit an ask_user SSE event and await a str resolution."""
    question_id = f"q_{uuid.uuid4().hex[:8]}"
    loop = asyncio.get_event_loop()
    future: asyncio.Future[str] = loop.create_future()
    _input_futures[question_id] = future
    await _emit(
        {
            "type": "ask_user",
            "question_id": question_id,
            "question": question,
        }
    )
    try:
        return await future
    finally:
        _input_futures.pop(question_id, None)


def resolve_user_input(question_id: str, answer: str) -> bool:
    """Resolve the string gate for a pending user-input request."""
    future = _input_futures.get(question_id)
    if future is None or future.done():
        return False
    future.set_result(answer)
    return True
