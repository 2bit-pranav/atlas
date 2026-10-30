"""Drive a running Atlas through its HTTP API, the way the web UI does.

Used by the live checks (real model, real tools). A run is followed through
its event stream; approval cards are answered by a policy function, and the
result is a `Turn` summary: status, timing, tool calls, approvals, answer.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

Approver = Callable[[dict[str, Any]], bool]


@dataclass
class Turn:
    label: str
    status: str | None = None
    error: str | None = None
    seconds: float = 0.0
    answer: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    context_used: int | None = None
    turn_id: str | None = None

    def used(self, name: str) -> bool:
        return any(t["name"] == name for t in self.tools)

    def describe(self) -> str:
        lines = [f"=== {self.label}  [{self.status}] {self.seconds:.1f}s  ctx={self.context_used}"]
        for t in self.tools:
            args = json.dumps(t.get("args"), ensure_ascii=False)[:160]
            lines.append(f"  tool {t['name']} {t.get('status', '?')}: {args}")
        for a in self.approvals:
            lines.append(f"  APPROVAL {a['kind']} allow={a['allow']}: {str(a['command'])[:120]}")
        if self.error:
            lines.append(f"  ERROR: {self.error}")
        lines.append("  answer: " + self.answer.replace("\n", " | ")[:600])
        return "\n".join(lines)


class Atlas:
    def __init__(self, url: str) -> None:
        self.c = httpx.Client(base_url=url.rstrip("/") + "/api", timeout=60)

    # --------------------------------------------------------------- chats --

    def new_chat(self, title: str = "") -> str:
        r = self.c.post("/chats", json={"title": title})
        r.raise_for_status()
        return r.json()["id"]

    def delete_chat(self, chat_id: str) -> None:
        self.c.delete(f"/chats/{chat_id}")

    def ask(self, chat: str, text: str, *, approve: Approver | None = None,
            thinking: bool = True, label: str = "") -> Turn:
        r = self.c.post(f"/chats/{chat}/messages", json={"text": text, "files": [], "thinking": thinking})
        if r.status_code == 409:
            # A chat whose last turn failed is retried or edited, never continued.
            return Turn(label=label or text[:50], status="refused", error=r.json().get("detail"))
        r.raise_for_status()
        return self._follow(r.json()["run"], approve, label or text[:50])

    def retry(self, turn_id: str, *, approve: Approver | None = None, thinking: bool = True,
              label: str = "retry") -> Turn:
        r = self.c.post(f"/turns/{turn_id}/retry", json={"thinking": thinking})
        r.raise_for_status()
        return self._follow(r.json()["run"], approve, label)

    def chat(self, chat_id: str) -> dict[str, Any]:
        return self.c.get(f"/chats/{chat_id}").json()

    # ------------------------------------------------------------ settings --

    def settings(self) -> dict[str, Any]:
        return self.c.get("/settings").json()["values"]

    def put_settings(self, patch: dict[str, Any]) -> None:
        """Save settings, then wait for MCP servers to settle: changing the
        allowed folders reconnects the filesystem server."""
        self.c.put("/settings", json=patch).raise_for_status()
        deadline = time.time() + 90
        while time.time() < deadline:
            if not any(s["status"] == "connecting" for s in self.c.get("/mcp").json()):
                return
            time.sleep(1)

    # -------------------------------------------------------------- events --

    def _follow(self, run: dict[str, Any], approve: Approver | None, label: str) -> Turn:
        turn = Turn(label=label)
        t0 = time.time()
        with self.c.stream("GET", f"/runs/{run['id']}/events?after=0", timeout=None,
                           headers={"Accept": "text/event-stream"}) as stream:
            buffer = ""
            for chunk in stream.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    for line in frame.split("\n"):
                        if line.startswith("data: ") and self._event(json.loads(line[6:]), run, turn, approve):
                            turn.seconds = time.time() - t0
                            return turn
        turn.seconds = time.time() - t0
        turn.status = turn.status or "stream-ended"
        return turn

    def _event(self, ev: dict[str, Any], run: dict[str, Any], turn: Turn, approve: Approver | None) -> bool:
        """Record one event; True when the run is over."""
        kind = ev["type"]
        if kind == "run_started":
            turn.turn_id = ev.get("turn_id")
        elif kind == "tool_start":
            turn.tools.append({"name": ev["name"], "args": ev.get("args")})
        elif kind == "tool_end":
            for t in reversed(turn.tools):
                if t["name"] == ev["name"] and "status" not in t:
                    t["status"], t["out"] = ev["status"], ev.get("text", "")
                    break
        elif kind == "text_delta":
            turn.answer += ev["text"]
        elif kind == "approval_request":
            allow = bool(approve(ev)) if approve else False
            turn.approvals.append({"kind": ev["kind"], "command": ev.get("command"), "allow": allow})
            self.c.post(f"/runs/{run['id']}/approvals/{ev['id']}", json={"allow": allow})
        elif kind == "stats":
            turn.context_used = ev.get("context_used")
        elif kind in ("done", "error"):
            turn.status, turn.error = ev.get("status"), ev.get("message")
            turn.answer = turn.answer.strip()
            return True
        return False
