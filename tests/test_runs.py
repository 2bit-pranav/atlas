"""Runs (server/runs.py): one active run, approvals, client
calls, cancel, and replaying the event stream from a sequence number."""

from __future__ import annotations

import asyncio

import pytest

from server.runs import RunConflict, RunManager


def test_only_one_run_at_a_time() -> None:
    runs = RunManager()
    first = runs.start("chat", "t1")
    with pytest.raises(RunConflict):
        runs.start("chat", "t2")
    with pytest.raises(RunConflict):
        runs.ensure_available()
    first.finish("completed")
    runs.adopt(first)
    runs.start("chat", "t3")                            # the slot is free again


def test_approval_is_answered() -> None:
    async def scenario() -> tuple[str, str]:
        run = RunManager().start("chat", "t")
        allowed = asyncio.create_task(run.request_approval("access", {"command": "read x"}, timeout=5))
        await asyncio.sleep(0)
        request = next(e for e in run.events if e["type"] == "approval_request")
        assert run.answer(request["id"], True)
        assert not run.answer(request["id"], False)     # answered once only
        denied = asyncio.create_task(run.request_approval("install", {"command": "pip x"}, timeout=5))
        await asyncio.sleep(0)
        second = [e for e in run.events if e["type"] == "approval_request"][-1]
        run.answer(second["id"], False)
        return await allowed, await denied

    assert asyncio.run(scenario()) == ("allowed", "denied")


def test_unanswered_approval_expires_as_no() -> None:
    async def scenario() -> tuple[str, list[str]]:
        run = RunManager().start("chat", "t")
        decision = await run.request_approval("access", {"command": "read x"}, timeout=0.05)
        return decision, [e["type"] for e in run.events]

    decision, events = asyncio.run(scenario())
    assert decision == "expired"
    assert events == ["approval_request", "approval_result"]


def test_cancel_denies_what_is_pending() -> None:
    async def scenario() -> tuple[str, dict]:
        runs = RunManager()
        run = runs.start("chat", "t")
        approval = asyncio.create_task(run.request_approval("access", {}, timeout=30))
        call = asyncio.create_task(run.client_call("read", {}, timeout=30))
        await asyncio.sleep(0)
        runs.cancel(run.id)
        assert run.cancel.is_set()
        return await approval, await call

    decision, result = asyncio.run(scenario())
    assert decision == "denied"
    assert "cancelled" in result["error"]


def test_client_call_round_trip_and_timeout() -> None:
    async def scenario() -> tuple[dict, dict]:
        run = RunManager().start("chat", "t")
        task = asyncio.create_task(run.client_call("read", {"view": "text"}, timeout=5))
        await asyncio.sleep(0)
        call = next(e for e in run.events if e["type"] == "client_call")
        assert call["op"] == "read" and call["args"] == {"view": "text"}
        assert run.resolve_call(call["id"], {"content": "page text"})
        late = await run.client_call("read", {}, timeout=0.05)
        return await task, late

    answered, late = asyncio.run(scenario())
    assert answered == {"content": "page text"}
    assert "did not answer" in late["error"]


def test_stream_replays_from_a_sequence_number() -> None:
    async def scenario() -> list[int]:
        runs = RunManager()
        run = runs.start("chat", "t")
        for i in range(3):
            run.emit({"type": "text_delta", "text": str(i)})
        run.finish("completed")
        return [e["seq"] async for e in runs.stream(run, after=2)]

    seqs = asyncio.run(scenario())
    assert seqs[0] == 2 and seqs == list(range(2, 2 + len(seqs)))


def test_finish_is_final() -> None:
    run = RunManager().start("chat", "t")
    run.finish("cancelled")
    run.finish("completed")
    assert run.status == "cancelled" and run.events[-1]["type"] == "done"
