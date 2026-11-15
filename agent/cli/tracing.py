"""`atlas trace` and `atlas replay`: what a run did, from its trace (agent/common/trace.py)."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from pathlib import Path
from typing import Any

from agent.common import trace


def _brief(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _secs(ms: float | int | None) -> str:
    return f"{(ms or 0) / 1000:.1f} s"


def summary(records: list[dict[str, Any]]) -> list[str]:
    """The run as an indented tree: each model call, then what followed it."""
    out: list[str] = []
    start = next((r for r in records if r.get("type") == "run"), {})
    end = next((r for r in records if r.get("type") == "end"), None)
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(records[0]["t"])) if records else "?"
    took = f" · {records[-1]['t'] - records[0]['t']:.1f} s" if len(records) > 1 else ""
    status = end["status"] if end else "no end recorded (still running, or the backend stopped)"
    out.append(f"run {start.get('run', '?')} · {when} · {start.get('model', '?')} · thinking "
               f"{'on' if start.get('thinking') else 'off'} · {start.get('mode', '?')} mode · {status}{took}")
    if start.get("page"):
        out.append(f"  page    {start['page']}")
    for r in records:
        kind = r.get("type")
        if kind == "model_request":
            messages = r["body"].get("messages") or []
            out.append(f"  call {r['call']}  {len(messages)} messages, {len(r['body'].get('tools') or [])} tools")
        elif kind == "model_response":
            t = r.get("timings") or {}
            calls = ", ".join(f"{c['name']}({_brief(c['arguments'], 60)})" for c in r.get("tool_calls") or [])
            out.append(f"    read {t.get('prompt_n', '?')} new + {t.get('cache_n', '?')} cached in "
                       f"{_secs(t.get('prompt_ms'))} · wrote {t.get('predicted_n', '?')} in {_secs(t.get('predicted_ms'))}"
                       f" · {r.get('finish_reason') or '?'}")
            if r.get("reasoning"):
                out.append(f"    thought  {_brief(r['reasoning'])}")
            if r.get("text"):
                out.append(f"    said     {_brief(r['text'])}")
            if calls:
                out.append(f"    asked    {calls}")
        elif kind == "model_error":
            out.append(f"    ERROR    {_brief(r.get('error'), 200)}")
        elif kind == "policy":
            what = r.get("reason") or r.get("detail") or r.get("asks") or r.get("args") or ""
            out.append(f"    policy   {r.get('step')} · {r.get('tool', '')} · {r.get('verdict')} · {_brief(what)}")
        elif kind == "event":
            e = r.get("event") or {}
            if e.get("type") == "tool_end":
                out.append(f"    tool     {e.get('name', e.get('id'))} → {e.get('status')} · {_brief(e.get('text', ''))}")
            elif e.get("type") in ("model_retry", "resumed", "tainted"):
                out.append(f"    {e['type']}")
        elif kind == "end" and r.get("error"):
            out.append(f"  error   {r['error']}")
    return out


def prompt(records: list[dict[str, Any]], call: int) -> list[str]:
    """Call `call`'s request, message by message, in full."""
    sent = next((r for r in records if r.get("type") == "model_request" and r.get("call") == call), None)
    if sent is None:
        return [f"no model call {call} in this trace"]
    body = sent["body"]
    out = [f"call {call}: " + ", ".join(f"{k}={body[k]}" for k in ("temperature", "max_tokens", "seed") if k in body)]
    for m in body.get("messages") or []:
        content = m.get("content")
        if isinstance(content, list):
            content = "\n".join(p.get("text", f"[{p.get('type', 'part')}]") for p in content if isinstance(p, dict))
        out.append(f"\n===== {m.get('role')} =====")
        if m.get("reasoning_content"):
            out.append(f"[reasoning]\n{m['reasoning_content']}\n[/reasoning]")
        out.append(str(content or ""))
        for c in m.get("tool_calls") or []:
            out.append(f"[tool call] {c.get('function', {}).get('name')} {c.get('function', {}).get('arguments')}")
    out.append(f"\n===== {len(body.get('tools') or [])} tools: "
               + ", ".join(t.get("function", {}).get("name", "?") for t in body.get("tools") or []))
    return out


def cmd_trace(args: argparse.Namespace, data_dir: Path) -> int:
    path = trace.find(data_dir, args.run)
    if path is None:
        print(f"no trace{' for run ' + args.run if args.run else ''} in {trace.traces_dir(data_dir)}", file=sys.stderr)
        return 1
    records = trace.read(path)
    lines = prompt(records, args.prompt) if args.prompt else summary(records)
    print("\n".join(lines))
    print(f"\n{path}", file=sys.stderr)
    return 0


def cmd_replay(args: argparse.Namespace, backend_port: int) -> int:
    import httpx

    try:
        response = httpx.post(f"http://127.0.0.1:{backend_port}/api/traces/{args.run}/replay",
                              params={"call": args.call}, timeout=660)
    except httpx.HTTPError:
        print("the backend is not running (`atlas start`)", file=sys.stderr)
        return 1
    if response.status_code != 200:
        print(response.json().get("detail", response.text) if response.headers.get("content-type", "").startswith(
            "application/json") else response.text, file=sys.stderr)
        return 1
    result = response.json()
    then, now = result.get("then") or {}, result["now"]

    def shown(r: dict[str, Any]) -> list[str]:
        calls = [f"[tool call] {c['name']} {c['arguments']}" for c in r.get("tool_calls") or []]
        return [*(r.get("text") or "").splitlines(), *calls]

    diff = list(difflib.unified_diff(shown(then), shown(now), "then", "now", lineterm=""))
    print(f"run {result['run']}, call {result['call']}: "
          + ("the same answer" if not diff else "a different answer"))
    print("\n".join(diff) if diff else "\n".join(shown(now)))
    return 0


__all__ = ["cmd_replay", "cmd_trace", "prompt", "summary"]
