"""The output rail: every figure in what a turn produces must come from somewhere.

The hard tasks' worst failure was a number the model typed: totals made up
for a report, a total row added wrong, an order left out (2026-11-14). Every
such number appears in no tool result. So:

- sources are every number in the user's messages and in every tool result
  in the chat's history (a file read, a query, a `calculate`, a web page);
- checked are the numbers the model typed into a document (`create_document`
  content without its {{references}}, which code fills from the files;
  `edit_docx` and `set_cell` values), and its answer when the turn used a tool;
- a figure matches a source loosely: 1,340 is 1340, and 59,657.4 or 59,658 is
  59,657.38 rounded. Small whole numbers (up to 10), years, dates, times and
  digits inside a file name are not checked.

A document with figures from nowhere sends the turn back once, naming them;
whatever is still unsourced at the end is shown to the user as a notice. The
pipelines (`extract_table`, ...) check their own values and are not looked at.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent, AfterToolCallEvent, BeforeInvocationEvent

from agent.tools.documents.references import REFERENCE

#: A number as written: 1,340  48,900.50  4.2  -3  12%. Digits glued to letters (inv-7301, Q3, A1) are not.
_NUMBER = re.compile(r"(?<![\w.\-/:])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w/:])|(?<![\w.\-/:,])-?\d+(?:\.\d+)?(?![\w/:]|,\d{3})")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[:.]\d{2}(?::\d{2})?\s*(?:am|pm)?\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", re.I)
_LIST_MARK = re.compile(r"^\s*(?:\d+[.)]|r\d+:|\|?\s*#?\s*\d+\s*\|)\s", re.M)
#: Typed into these tools, a figure is the model's own.
WRITERS = {"create_document": ("content",), "edit_docx": ("text",), "set_cell": ("value",)}


def _value(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def numbers(text: str) -> list[str]:
    """The figures in `text` that need a source."""
    text = _LIST_MARK.sub(" ", _DATE.sub(" ", text))
    out = []
    for token in _NUMBER.findall(text):
        v = _value(token)
        if v is None:
            continue
        if v == v.to_integral_value() and (abs(v) <= 10 or (1900 <= v <= 2100 and "," not in token)):
            continue
        out.append(token)
    return out


#: Sources are read leniently: CSV fields come right after a comma (`O1036,North,11,110.42`).
_ANY_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def source_values(texts: list[str]) -> set[Decimal]:
    found: set[Decimal] = set()
    for t in texts:
        for token in _ANY_NUMBER.findall(t) + re.findall(r"\d+(?:\.\d+)?", t):
            if (v := _value(token)) is not None:
                found.add(v)
    return found


def sourced(token: str, sources: set[Decimal]) -> bool:
    v = _value(token)
    if v is None:
        return True
    v = abs(v)
    if v in sources:
        return True
    exponent = v.as_tuple().exponent
    q = Decimal(1).scaleb(min(0, exponent if isinstance(exponent, int) else 0))   # 59,657.4 -> 0.1
    return any(s.quantize(q, ROUND_HALF_UP) == v for s in sources)   # a source, rounded as written


def unsourced(text: str, sources: set[Decimal]) -> list[str]:
    return list(dict.fromkeys(t for t in numbers(text) if not sourced(t, sources)))


def _texts(messages: list[dict[str, Any]]) -> list[str]:
    """What the user wrote and what tools returned, in the whole history: the sources."""
    out = []
    for m in messages:
        for b in m.get("content") or []:
            if m.get("role") == "user" and "text" in b:
                out.append(str(b["text"]))
            if "toolResult" in b:
                out += [str(c.get("text", "")) for c in b["toolResult"].get("content") or [] if isinstance(c, dict)]
    return out


class Provenance(HookProvider):
    def __init__(self, notify: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._notify = notify
        self._typed: list[tuple[str, str]] = []     # (where, the text the model typed)
        self._tools = 0
        self._resumed = self._resuming = False

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._before)
        registry.add_callback(AfterToolCallEvent, self._after_tool)
        registry.add_callback(AfterInvocationEvent, self._after)

    def _before(self, event: Any) -> None:
        if self._resuming:
            self._resuming = False
            return
        self._typed.clear()
        self._tools = 0
        self._resumed = False

    def _after_tool(self, event: Any) -> None:
        self._tools += 1
        name = str(event.tool_use.get("name", ""))
        if name not in WRITERS or (event.result or {}).get("status") == "error":
            return
        args = event.tool_use.get("input") or {}
        typed = " ".join(str(args.get(k) or "") for k in WRITERS[name])
        where = str(args.get("path") or name)
        # The file's figures come from its references, filled in by code: only what was typed is the model's.
        self._typed = [(w, t) for w, t in self._typed if w != where] + [(where, REFERENCE.sub(" ", typed))]

    def _after(self, event: Any) -> None:
        result = event.result
        if result is None or getattr(result, "stop_reason", None) != "end_turn":
            return
        sources = source_values(_texts(getattr(event.agent, "messages", None) or []))
        docs = {w: bad for w, t in self._typed if (bad := unsourced(t, sources))}
        if docs and not self._resumed and not event.resume:
            self._resumed = self._resuming = True
            listed = "; ".join(f"{w}: {', '.join(b[:8])}" for w, b in docs.items())
            self._note("send back", listed)
            event.resume = (f"[Atlas] Not done yet: these figures are in no file, tool result or message, so they "
                            f"were typed, not copied: {listed}. Make the document again with create_document (the "
                            "same name replaces your draft), putting rows and totals in with references such as "
                            "{{file.csv sql: SELECT ...}} or numbers from calculate, never typed.")
            return
        answer = _text_of(getattr(result, "message", None)) if self._tools else ""
        loose = {**docs, **({"the answer": bad} if (bad := unsourced(answer, sources)) else {})}
        if loose:
            listed = "; ".join(f"{w}: {', '.join(b[:8])}" for w, b in loose.items())
            self._note("flag", listed)
            if self._notify is not None:
                self._notify({"type": "notice", "level": "warning",
                              "text": f"Figures not found in any file, tool result or message: {listed}. "
                                      "Check them before relying on them."})

    def _note(self, verdict: str, reason: str) -> None:
        if self._notify is not None:
            self._notify({"type": "policy", "step": "output", "rail": "provenance", "verdict": verdict,
                          "reason": reason[:300]})


def _text_of(message: Any) -> str:
    content = (message or {}).get("content") if isinstance(message, dict) else None
    return "".join(str(b.get("text", "")) for b in content or [] if isinstance(b, dict))


__all__ = ["Provenance", "numbers", "source_values", "sourced", "unsourced"]
