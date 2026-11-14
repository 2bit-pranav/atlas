"""The egress gate: one check in front of everything that leaves the machine (plan 4.2).

Before, each channel had its own rule or none: `web_search` checked its
query, `read_url` its address (since 2026-11-12), and MCP arguments, a PDF
link or a skill script's address nothing. Here every outbound string, from any
channel, gets the same rails before the tool runs:

- shape: no file path, no long number, no address that carries either
  (the web tools' own rules, `web.query_refusal` and `web._carried`);
- budget: once the chat holds outside content, at most `BUDGET` characters
  leave per turn, so a page cannot drain a document a query at a time;
- overlap: no run of `RUN_WORDS` words copied from a document this chat read
  (a phrase query on the ingest store), unless the user typed it themselves.

Registered before `ToolPolicy`: a call refused here never shows a card first.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

from agent.safety.rails import PASS, Verdict, run_rails

#: Characters that may leave per turn once the chat holds outside content.
BUDGET = 600
#: Words in a row that make a string a copy of a document: long enough for a paper's title.
RUN_WORDS = 12
_URL = re.compile(r"^https?://", re.I)


def outbound(name: str, args: dict[str, Any], tool: Any, untrusted: Callable[[str], bool]) -> list[str]:
    """The strings a call sends off the machine."""
    if name == "web_search":
        return [str(args.get("query") or "")]
    if name == "read_url":
        return [str(args.get("url") or ""), str(args.get("question") or "")]
    if name == "read_pdf" and _URL.match(str(args.get("path") or "")):
        return [str(args["path"])]
    if name == "run_skill":
        return [str(a) for a in args.get("args") or [] if _URL.match(str(a))]
    if isinstance(tool, MCPAgentTool) and untrusted(name):
        return _strings(args)
    return []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


class _Ctx:
    def __init__(self, guard: EgressGuard) -> None:
        self.guard = guard


class Shape:
    name, stage = "shape", "egress"

    def check(self, text: str, ctx: _Ctx) -> Verdict:
        from agent.tools.web import _carried, query_refusal

        if _URL.match(text):
            why = _carried(text, urlparse(text))
        else:
            why = query_refusal(text)
        return Verdict("refuse", why) if why else PASS


class Budget:
    name, stage = "budget", "egress"

    def check(self, text: str, ctx: _Ctx) -> Verdict:
        g = ctx.guard
        if not g.tainted() or g.spent + len(text) <= BUDGET:
            return PASS
        return Verdict("refuse", f"this turn has sent {g.spent} characters out since outside content entered the "
                                 f"chat; at most {BUDGET} may leave. Ask the user before sending more.")


class Overlap:
    name, stage = "overlap", "egress"

    def check(self, text: str, ctx: _Ctx) -> Verdict:
        g = ctx.guard
        words = re.findall(r"\w+", text.lower())
        typed = " ".join(re.findall(r"\w+", g.request.lower()))
        for i in range(0, max(0, len(words) - RUN_WORDS + 1)):
            run = words[i:i + RUN_WORDS]
            if " ".join(run) in typed:
                continue
            if g.store is not None and g.store.holds_phrase(g.chat, run):
                return Verdict("refuse", "it repeats a passage of a document this chat read "
                                         f"(\"{' '.join(run[:6])} ...\"); the user's documents never leave the "
                                         "machine. Describe what to find in a few words of your own.")
        return PASS


RAILS = [Shape(), Budget(), Overlap()]


class EgressGuard(HookProvider):
    def __init__(self, *, store: Any, chat: str, request: str, tainted: Callable[[], bool],
                 untrusted: Callable[[str], bool] | None = None,
                 observer: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.store, self.chat, self.request = store, chat, request or ""
        self.tainted = tainted
        self.untrusted = untrusted or (lambda _name: False)
        self.observer = observer
        self.spent = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)

    def _before(self, event: BeforeToolCallEvent) -> None:
        name = str(event.tool_use.get("name", ""))
        sent = [s for s in outbound(name, event.tool_use.get("input") or {}, event.selected_tool, self.untrusted) if s]
        ctx = _Ctx(self)
        for text in sent:
            v = run_rails(RAILS, "egress", text, ctx, self.observer)
            if v.action == "refuse":
                event.cancel_tool = f"Refused: nothing was sent. {v.reason}"
                return
        if self.tainted():
            self.spent += sum(len(s) for s in sent)


__all__ = ["BUDGET", "RUN_WORDS", "EgressGuard", "outbound"]
