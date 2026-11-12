"""Code says when a turn is done, not the model stopping.

Strands ends a turn when the model stops calling tools. In the harder document
tasks (2026-11-12) that was often too early, in ways code can see:

- a document the turn made or changed does not open (CSV text saved as
  `north.xlsx` by a script it wrote);
- the file the user asked for was never made (5 of 19 runs);
- the last message only says what it will do next ("Now I will create the
  spreadsheet.") and stops;
- asked for a summary, it read page 1 of 16.

At the end of a turn the first of these that holds sends the model back once,
saying exactly what is missing. One resume per turn, and none after the
failure recovery already resumed it (`tool_recovery.py`).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent, AfterToolCallEvent, BeforeInvocationEvent

from agent.recovery.model_retry import Notify

logger = logging.getLogger(__name__)

#: A file a request asks to be made: its name after a word that makes something, in the same sentence.
_ASKED = re.compile(r"\b(?:make|create|save|write|export|produce|generate|build|turn|convert|put|into|as|named|called)"
                    r"\b[^.\n]{0,60}?\b([\w][\w()-]*\.(?:docx|xlsx|pdf|csv|md|txt))\b", re.I)
_SUMMARY = re.compile(r"\bsummar(?:y|ies|ise|ize|ising|izing)\b", re.I)
#: A last message that only announces the next step.
_INTENT = re.compile(r"(?:^|[.!:\n]\s*)(?:ok(?:ay)?[,.!]?\s*|sure[,.!]?\s*|now,?\s*|next,?\s*)?"
                     r"(?:i will|i'll|let me|i am going to|i'm going to)\s+(?:now\s+)?"
                     r"(?:create|make|write|read|open|check|calculate|compute|save|build|generate|put|extract|"
                     r"summari[sz]e|start|search|fetch|convert|add|update|edit|fill|compile|combine|merge|draft|"
                     r"prepare|go through|look)\b[^.!?\n]*[.!:]?\s*$", re.I)
_PAGE = re.compile(r"^--- page (\d+) of (\d+)", re.M)
#: A summary of a PDF longer than this is not expected to read every page.
#: shortcut: a fixed size, until summaries go through the section pipeline (plan 3.4).
SUMMARY_PAGES = 40


def document_problem(path: Path) -> str | None:
    """Why `path` does not open as the document its name says, or None."""
    from agent.tools.documents.docx import _check_docx
    from agent.tools.documents.pdf import _check_pdf
    from agent.tools.documents.xlsx import _check_xlsx

    check = {".docx": _check_docx, ".xlsx": _check_xlsx, ".pdf": _check_pdf}.get(path.suffix.lower())
    if check is None or not path.is_file():
        return None
    try:
        check(path)
    except Exception as exc:  # noqa: BLE001 - any failure to open is the answer
        return f"{type(exc).__name__}: {str(exc)[:200]}"
    return None


class DoneCheck(HookProvider):
    def __init__(self, workspace: Path, request: str, notify: Notify | None = None,
                 place: Any = None) -> None:
        self.workspace = workspace
        self.request = request or ""
        #: Where a file name lands, as every tool places it (Scope.place): a file saved into an allowed folder.
        self.place = place or (lambda name: workspace / name)
        self._notify = notify
        self._before: dict[str, tuple[int, int]] = {}
        self._pages: dict[str, tuple[set[int], int]] = {}
        self._resumed = False
        self._resuming = False

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._before_invocation)
        registry.add_callback(AfterToolCallEvent, self._after_tool)
        registry.add_callback(AfterInvocationEvent, self._after_invocation)

    def _before_invocation(self, event: BeforeInvocationEvent) -> None:
        if self._resuming:            # the same turn, sent back: keep what it had done
            self._resuming = False
            return
        self._before = scan(self.workspace)
        self._pages.clear()
        self._resumed = False

    def _after_tool(self, event: AfterToolCallEvent) -> None:
        if event.tool_use.get("name") != "read_pdf" or (event.result or {}).get("status") == "error":
            return
        text = "\n".join(str(b.get("text", "")) for b in (event.result or {}).get("content") or [] if isinstance(b, dict))
        name = text.split(":", 1)[0].strip()
        for page, total in _PAGE.findall(text):
            seen, _ = self._pages.get(name, (set(), int(total)))
            seen.add(int(page))
            self._pages[name] = (seen, int(total))

    def _after_invocation(self, event: AfterInvocationEvent) -> None:
        result = event.result
        if self._resumed or event.resume or result is None or getattr(result, "stop_reason", None) != "end_turn":
            return
        why = self.missing(_text_of(getattr(result, "message", None)))
        if why is None:
            return
        self._resumed = self._resuming = True
        logger.info("turn not done (%s); resuming once", why[:80])
        if self._notify is not None:
            self._notify({"type": "resumed", "reason": "not done"})
        event.resume = f"[Atlas] Not done yet: {why}"

    def missing(self, last: str) -> str | None:
        """What is missing, in words for the model, or None when the turn looks done."""
        after = scan(self.workspace)
        changed = [n for n, v in after.items() if self._before.get(n) != v]
        for name in changed:
            if (problem := document_problem(self.workspace / name)) is not None:
                return (f"{name} does not open as a {Path(name).suffix.lower()} file ({problem}); it is "
                        "broken. Make it again with create_document, from Markdown, and check it was created.")
        made = {Path(n).name.lower() for n in after}
        had = {Path(n).name.lower() for n in self._before}
        inputs = re.compile(r"\b(?:of|from|in|on|about|with|using)\s+$", re.I)   # "a summary of review.pdf"
        for asked in dict.fromkeys(m.group(1) for m in _ASKED.finditer(self.request)
                                   if not inputs.search(self.request[:m.start(1)])):
            if asked.lower() in made or asked.lower() in had or Path(self.place(asked)).is_file():
                continue
            return (f"you were asked for {asked} and it does not exist. Make it now "
                    "(create_document), then tell the user it is ready.")
        if _INTENT.search(last.strip()) and not changed:
            return ("you said what you would do next but stopped before doing it. Do it now: call the "
                    "tool, then answer.")
        if _SUMMARY.search(self.request):
            for name, (seen, total) in self._pages.items():
                if total <= SUMMARY_PAGES and len(seen) < total:
                    rest = sorted(set(range(1, total + 1)) - seen)
                    return (f"you were asked for a summary and read {len(seen)} of {total} pages of {name}. "
                            f"Read the rest (read_pdf(path=\"{name}\", pages=\"{rest[0]}-{rest[-1]}\")), "
                            "then write the summary from all of it.")
        return None


def scan(root: Path) -> dict[str, tuple[int, int]]:
    """`relative/path -> (size, mtime_ns)` for every file in a workspace.

    Dot-files and dot-folders are Atlas's own bookkeeping (temp files, images a
    reader extracted): not the user's files."""
    out: dict[str, tuple[int, int]] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return out


def _text_of(message: Any) -> str:
    content = (message or {}).get("content") if isinstance(message, dict) else None
    return "".join(str(b.get("text", "")) for b in content or [] if isinstance(b, dict))


__all__ = ["SUMMARY_PAGES", "DoneCheck", "document_problem", "scan"]
