"""Runs: their state, the event stream, approvals, client calls, cancel."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from agent.common import trace
from agent.config import paths
from agent.model import server as llama
from server.schemas import (
    Answer,
    CallResult,
)
from server.views import _run_view


def register(api: Any, state: Any) -> None:
    # ------------------------------------------------------------- traces --

    @api.post("/traces/{run_id}/replay")
    async def replay(run_id: str, call: int = 1) -> dict[str, Any]:
        """Send one saved model request again, as it was, and return what comes back now.

        For `atlas replay`: the llama-server key lives only in the backend. Not an
        extension route (security.EXTENSION_ROUTES): a trace is a whole conversation.
        """
        if state.runs.active() is not None:
            raise HTTPException(409, "a run is active; replay when it has finished")
        path = trace.find(paths.data_dir(state.settings), run_id) if len(run_id) >= 6 else None
        if path is None:
            raise HTTPException(404, f"no trace for run {run_id}")
        records = await asyncio.to_thread(trace.read, path)
        sent = next((r for r in records if r.get("type") == "model_request" and r.get("call") == call), None)
        if sent is None:
            raise HTTPException(404, f"run {run_id} has no model call {call}")
        then = next((r for r in records if r.get("type") == "model_response" and r.get("call") == call), None)
        body = {**sent["body"], "stream": False}
        body.pop("stream_options", None)
        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(f"http://127.0.0.1:{state.settings.ports.llama}/v1/chat/completions",
                                         json=body, headers=llama.auth_headers())
        if response.status_code >= 400:
            raise HTTPException(502, f"llama-server answered {response.status_code}: {response.text[:500]}")
        message = (response.json().get("choices") or [{}])[0].get("message") or {}
        now = {"text": message.get("content") or "", "reasoning": message.get("reasoning_content") or "",
               "tool_calls": [{"name": (c.get("function") or {}).get("name", ""),
                               "arguments": (c.get("function") or {}).get("arguments", "")}
                              for c in message.get("tool_calls") or []]}
        return {"run": path.stem.split("-", 1)[-1], "call": call, "then": then, "now": now}

    # --------------------------------------------------------------- runs --

    @api.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        return {**_run_view(run), "error": run.error, "events": len(run.events)}

    @api.get("/runs/{run_id}/events")
    async def run_events(run_id: str, after: int = 0) -> StreamingResponse:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")

        async def sse() -> Any:
            # Replay then follow, so a reloaded client resumes with no gaps and
            # no duplicates. `after` is the first seq the client has NOT seen.
            async for event in state.runs.stream(run, after):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @api.post("/runs/{run_id}/approvals/{approval_id}")
    async def answer_approval(run_id: str, approval_id: str, body: Answer) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        decision = run.answer(approval_id, body.allow, body.scope)
        if decision is None:
            raise HTTPException(409, "that question was already answered or has expired")
        return {"id": approval_id, "decision": decision}

    @api.post("/runs/{run_id}/calls/{call_id}")
    async def answer_call(run_id: str, call_id: str, body: CallResult) -> dict[str, Any]:
        """The side panel's result for a page operation the run asked for."""
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        if not run.resolve_call(call_id, body.model_dump()):
            raise HTTPException(409, "that call was already answered or has timed out")
        return {"id": call_id}

    @api.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        state.runs.cancel(run_id)
        return _run_view(run)
