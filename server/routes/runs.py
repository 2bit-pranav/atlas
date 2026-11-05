"""Runs: their state, the event stream, approvals, client calls, cancel."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from server.schemas import (
    Answer,
    CallResult,
)
from server.views import _run_view


def register(api: Any, state: Any) -> None:
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
