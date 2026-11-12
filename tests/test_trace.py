"""A trace per run (agent/common/trace.py): every event, model call and policy decision, on disk as it happens."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from helpers import Asked, settings_file

from agent.common import trace
from agent.model.llamacpp import AtlasLlamaCppModel
from agent.safety.policy import ToolPolicy
from agent.safety.scope import Scope
from server.runs import Run
from server.state import Atlas
from server.transcript import Transcript


def _run(tmp_path: Path) -> Run:
    run = Run(id="r1", chat_id="c1", turn_id="t1", transcript=Transcript(32768))
    run.trace = trace.open_trace(tmp_path, "c1", "t1", "r1")
    return run


def test_a_run_writes_its_events_model_calls_and_decisions_as_they_happen(tmp_path) -> None:
    run = _run(tmp_path)
    run.emit({"type": "call_start"})
    run.observe({"type": "model_request", "body": {"messages": [{"role": "user", "content": "hi"}]}})
    run.observe({"type": "model_response", "text": "hello", "tool_calls": [], "finish_reason": "stop"})
    run.observe({"type": "policy", "step": "grid", "tool": "shell", "verdict": "refuse", "reason": "no"})
    run.emit({"type": "text_delta", "text": "hello"})
    path = run.trace.path
    written = trace.read(path)                              # on disk before the run ends
    assert [r["type"] for r in written] == ["event", "model_request", "model_response", "policy", "event"]
    assert written[1]["call"] == 1 and written[1]["body"]["messages"][0]["content"] == "hi"
    run.finish("completed")
    records = trace.read(path)
    assert records[-1] == {**records[-1], "type": "end", "status": "completed"}
    assert path == tmp_path / "traces" / "c1" / "t1-r1.jsonl"
    assert trace.find(tmp_path, "r1") == path and trace.find(tmp_path) == path
    assert trace.for_turn(tmp_path, "c1", "t1") == path


def test_each_model_call_keeps_its_own_numbers() -> None:
    t = Transcript(32768)
    for prompt_n, cache_n, predicted_n in ((4000, 0, 50), (120, 4050, 600)):
        t.fold({"type": "call_start"})
        t.call_timings({"prompt_n": prompt_n, "cache_n": cache_n, "predicted_n": predicted_n,
                        "prompt_ms": 2700.4, "predicted_ms": 7300.6})
    assert t.final_stats()["calls"] == [
        {"prompt_fresh": 4000, "prompt_cached": 0, "completion": 50, "prompt_ms": 2700, "generation_ms": 7301},
        {"prompt_fresh": 120, "prompt_cached": 4050, "completion": 600, "prompt_ms": 2700, "generation_ms": 7301}]


def test_policy_decisions_and_answers_are_written_down(tmp_path) -> None:
    noted: list[dict] = []
    asked = Asked("denied")
    policy = ToolPolicy(Scope(tmp_path / "ws", folders=[tmp_path / "docs"]), approver=asked, observer=noted.append)

    def call(name: str, args: dict) -> None:
        event = SimpleNamespace(tool_use={"name": name, "toolUseId": "t", "input": args},
                                selected_tool=SimpleNamespace(tool_name=name), cancel_tool=False)
        asyncio.run(policy._before(event))

    call("delete_file", {"path": str(tmp_path / "elsewhere" / "x.txt")})
    steps = [(n["step"], n["verdict"]) for n in noted]
    assert ("grid", "zones") in steps and ("approval", "denied") in steps and ("grid", "refuse") in steps
    zones = next(n for n in noted if n["verdict"] == "zones")["asks"]
    assert zones[0]["zone"] == "elsewhere" and zones[0]["action"] == "delete"
    assert all(n["type"] == "policy" and n["mode"] == "ask" for n in noted)


def test_an_interrupted_turn_shows_what_its_trace_recorded(tmp_path) -> None:
    path = settings_file(tmp_path)
    first = Atlas(path)
    chat = first.store.create_chat()["id"]
    turn = first.store.insert_turn(chat, "summarise", parent_turn_id=None, before_snap=None)
    t = trace.open_trace(tmp_path / "data", chat, turn["id"], "run42")
    for event in ({"type": "call_start"}, {"type": "text_delta", "text": "The report says "},
                  {"type": "tool_start", "id": "a", "name": "read_pdf", "args": {"path": "r.pdf"}}):
        t.write("event", event=event)
    t.close()
    first.close()                                           # the backend dies with the turn running

    second = Atlas(path)                                    # and starts again
    try:
        row = second.store.get_turn(turn["id"])
        assert row["status"] == "interrupted"
        render = json.loads(row["render_json"])
        assert render[0] == {"kind": "text", "text": "The report says "} and render[1]["name"] == "read_pdf"
        assert json.loads(row["stats_json"])["run_id"] == "run42" and "retry" in row["error"]
    finally:
        second.close()


def test_old_traces_are_swept_and_a_deleted_chat_takes_its_traces(tmp_path) -> None:
    old = trace.open_trace(tmp_path, "c1", "t1", "old")
    old.close()
    past = time.time() - (trace.KEEP_DAYS + 1) * 86400
    os.utime(old.path, (past, past))
    new = trace.open_trace(tmp_path, "c1", "t2", "new")      # opening sweeps
    new.close()
    assert not old.path.exists() and new.path.exists()
    trace.delete_chat(tmp_path, "c1")
    assert not (tmp_path / "traces" / "c1").exists()


def test_the_model_reports_its_exact_request_and_whole_response(monkeypatch) -> None:
    """Against a stand-in llama-server: the body sent, and what came back, for the trace. No key in either."""
    monkeypatch.setenv("ATLAS_LLAMA_KEY", "llama-secret")
    lines = [
        {"choices": [{"delta": {"reasoning_content": "Think. "}}]},
        {"choices": [{"delta": {"content": "Sure: "}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "calculate", "arguments": '{"ex'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'pression": "1+1"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "timings": {"prompt_n": 12, "predicted_n": 9}},
    ]
    body = "".join(f"data: {json.dumps(x)}\n\n" for x in lines) + "data: [DONE]\n\n"
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    seen: list[dict] = []
    model = AtlasLlamaCppModel(base_url="http://llama.test", observer=seen.append)
    model.client = httpx.AsyncClient(base_url="http://llama.test", transport=httpx.MockTransport(handler),
                                     headers=model.client.headers)

    async def go() -> None:
        async for _ in model.stream([{"role": "user", "content": [{"text": "1+1?"}]}], system_prompt="be brief"):
            pass

    asyncio.run(go())
    request = next(e for e in seen if e["type"] == "model_request")["body"]
    response = next(e for e in seen if e["type"] == "model_response")
    assert request == json.loads(sent[0].content)                          # exactly what was sent
    assert sent[0].headers["authorization"] == "Bearer llama-secret"       # the key went in the header...
    assert "llama-secret" not in json.dumps(seen)                          # ...and nowhere the trace sees
    assert response["text"] == "Sure: " and response["reasoning"] == "Think. "
    assert response["tool_calls"] == [{"name": "calculate", "arguments": '{"expression": "1+1"}'}]
    assert response["finish_reason"] == "tool_calls" and response["timings"]["prompt_n"] == 12


def test_a_failed_model_call_is_recorded(monkeypatch) -> None:
    seen: list[dict] = []
    model = AtlasLlamaCppModel(base_url="http://llama.test", observer=seen.append)
    model.client = httpx.AsyncClient(base_url="http://llama.test", transport=httpx.MockTransport(
        lambda r: httpx.Response(500, text="boom")))

    async def go() -> None:
        async for _ in model.stream([{"role": "user", "content": [{"text": "x"}]}]):
            pass

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(go())
    assert next(e for e in seen if e["type"] == "model_error")["error"].startswith("HTTP 500")


def _sample(data_dir: Path) -> Path:
    t = trace.open_trace(data_dir, "c1", "t1", "abcdef123456")
    t.write("run", chat="c1", turn="t1", run="abcdef123456", model="gemma", thinking=False, mode="ask")
    t.write("model_request", call=1, body={"temperature": 0.7, "messages": [
        {"role": "system", "content": "You are Atlas."}, {"role": "user", "content": "What is 2+2?"}],
        "tools": [{"function": {"name": "calculate"}}]})
    t.write("model_response", call=1, text="", reasoning="add them", finish_reason="tool_calls",
            tool_calls=[{"name": "calculate", "arguments": '{"expression": "2+2"}'}],
            timings={"prompt_n": 900, "cache_n": 0, "prompt_ms": 600, "predicted_n": 20, "predicted_ms": 250})
    t.write("policy", step="grid", tool="shell", verdict="refuse", reason="Atlas's own data")
    t.write("event", event={"type": "tool_end", "id": "a", "name": "calculate", "status": "success", "text": "4"})
    t.write("model_request", call=2, body={"messages": [{"role": "user", "content": "What is 2+2?"}]})
    t.write("model_response", call=2, text="It is 4.", finish_reason="stop", tool_calls=[], timings={})
    t.write("end", status="completed")
    t.close()
    return t.path


def test_atlas_trace_prints_the_run_and_a_calls_whole_prompt(tmp_path, capsys) -> None:
    from agent.cli.main import main

    settings = settings_file(tmp_path)
    _sample(tmp_path / "data")
    assert main(["--settings", str(settings), "trace"]) == 0
    tree = capsys.readouterr().out
    assert "run abcdef123456" in tree and "gemma" in tree and "completed" in tree
    assert "call 1  2 messages, 1 tools" in tree and "read 900 new + 0 cached in 0.6 s" in tree
    assert 'asked    calculate({"expression": "2+2"})' in tree and "policy   grid · shell · refuse" in tree
    assert "tool     calculate → success · 4" in tree and "said     It is 4." in tree
    assert main(["--settings", str(settings), "trace", "abcdef", "--prompt", "1"]) == 0
    full = capsys.readouterr().out
    assert "===== system =====\nYou are Atlas." in full and "temperature=0.7" in full and "1 tools: calculate" in full
    assert main(["--settings", str(settings), "trace", "nosuchrun"]) == 1


def test_replay_sends_the_saved_request_again(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import server.routes.runs as runs_routes
    from server.app import create_app

    app = create_app(settings_file(tmp_path))
    _sample(tmp_path / "data")
    sent: list[dict] = []

    def llama(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "It is four."}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(runs_routes.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(llama), **kw))
    try:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        r = client.post("/api/traces/abcdef/replay", params={"call": 2})
        assert r.status_code == 200, r.text
        assert sent[0]["stream"] is False and sent[0]["messages"][0]["content"] == "What is 2+2?"
        assert r.json()["then"]["text"] == "It is 4." and r.json()["now"]["text"] == "It is four."
        assert client.post("/api/traces/abcdef/replay", params={"call": 9}).status_code == 404
        token = (tmp_path / "data" / "pairing-token").read_text(encoding="utf-8").strip()
        ext = {"Origin": "chrome-extension://abc", "Authorization": f"Bearer {token}"}
        assert client.post("/api/traces/abcdef/replay", headers=ext).status_code == 403   # a whole conversation
    finally:
        app.state.atlas.close()
