"""Live checks: the demo tasks against a running Atlas and the real model.

    python tests/live/check_demo.py --url http://127.0.0.1:8001
    python tests/live/check_demo.py --url http://127.0.0.1:8001 invoices merge --trials 3

Run at every checkpoint (before fixes, after fixes, after the restructure) and
compare the summaries. Needs the GPU to itself: two llama-servers on one 4 GB
card slow both to ~9 tokens/s.

For the run, the target's `access.folders` is set to the fixtures' Desktop;
the previous value is put back afterwards, even on failure. Each scenario
starts from freshly built fixtures in a new chat; the chats are kept, so a
failure can be opened in the UI. Logs go to `.data/live/<timestamp>.log`.

Checks are only what code can decide: a file exists and parses, a number is in
the answer, a tool was called, a card was answered.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_api import Atlas, Turn  # noqa: E402
from fixtures import Fixtures, build  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
Result = dict[str, bool]


def _num(text: str) -> str:
    return text.replace(",", "")


def invoices(a: Atlas, fx: Fixtures, log: Callable[[Turn], None]) -> Result:
    chat = a.new_chat("live: invoices")
    t1 = a.ask(chat, "In Demo/Invoices there are this month's invoices. Read each one and put the vendor, date "
                     "and amount in a spreadsheet. Save it as October-expenses.xlsx in Demo/Reports.",
               approve=lambda ev: True, label="invoices 1/2")
    log(t1)
    t2 = a.ask(chat, "What's the total, and which vendor did I spend the most with? Write a one-page summary "
                     "as October-summary.pdf in the same folder.", approve=lambda ev: True, label="invoices 2/2")
    log(t2)
    sheet = fx.reports / "October-expenses.xlsx"
    rows: list[Any] = []
    if sheet.exists():
        from openpyxl import load_workbook
        rows = [r for r in load_workbook(sheet, data_only=True).active.iter_rows(values_only=True)]
    vendors = " ".join(str(c) for r in rows for c in r)
    return {
        "sheet has all 5 vendors": all(v in vendors for v in fx.totals),
        f"total {fx.total:,.2f} in answer": f"{fx.total:.2f}" in _num(t2.answer),
        f"top vendor {fx.top_vendor}": fx.top_vendor in t2.answer,
        "summary PDF written": (fx.reports / "October-summary.pdf").exists(),
        "sheet not overwritten": len(rows) >= 6,
        "used calculate": t2.used("calculate"),
    }


def merge(a: Atlas, fx: Fixtures, log: Callable[[Turn], None]) -> Result:
    chat = a.new_chat("live: merge")
    log(a.ask(chat, "Merge Demo/Assignment/assignment-part1.pdf and Demo/Assignment/assignment-part2.pdf into "
                    "one file, then make a Word version.", approve=lambda ev: True, label="merge 1/2"))
    log(a.ask(chat, 'In the Word file, change "Pranav Chandak" to "P. Chandak".', approve=lambda ev: True,
              label="merge 2/2"))
    workspace = Path(a.c.get("/settings").json()["paths"]["data"]) / "chats" / chat
    pdfs = [p for p in workspace.rglob("*.pdf")]
    docxs = [p for p in workspace.rglob("*.docx")]
    out: Result = {"merged PDF": bool(pdfs), "Word file": bool(docxs)}
    if pdfs:
        import fitz
        doc = fitz.open(pdfs[0])
        out["2 pages, an image each"] = len(doc) == 2 and all(p.get_images() for p in doc)
    if docxs:
        from docx import Document
        text = "\n".join(p.text for p in Document(docxs[0]).paragraphs)
        out["name changed once"] = text.count("P. Chandak") == 1 and "Pranav Chandak" not in text
    return out


QUESTIONS = [
    ("gst", "What is 18% GST on Rs. 2,750, and what is the total with GST?", ["495", "3245"], "calculate"),
    ("days", "How many days are there between 2 Oct 2026 and 15 Nov 2026?", ["44"], "dates"),
    ("weekday", "What day of the week is 26 January 2027?", ["Tuesday"], "dates"),
]


def maths(a: Atlas, fx: Fixtures, log: Callable[[Turn], None]) -> Result:
    out: Result = {}
    for key, question, expected, tool in QUESTIONS:
        t = a.ask(a.new_chat(f"live: {key}"), question, label=key)
        log(t)
        out[f"{key}: right"] = all(e in _num(t.answer) for e in expected)
        out[f"{key}: used {tool}"] = t.used(tool)
    return out


def access(a: Atlas, fx: Fixtures, log: Callable[[Turn], None]) -> Result:
    chat = a.new_chat("live: access")
    denied = a.ask(chat, f"Read {fx.notes}", approve=lambda ev: False, label="access deny")
    log(denied)
    folders = a.settings()["access.folders"]
    a.put_settings({"access.folders": [*folders, str(fx.notes.parent)]})
    try:
        allowed = a.ask(chat, f"I've allowed that folder now. Read {fx.notes} again.",
                        approve=lambda ev: False, label="access after allowing")
    finally:
        a.put_settings({"access.folders": folders})
    log(allowed)
    return {
        "card shown": any(x["kind"] == "access" for x in denied.approvals),
        "denied: not read": "PIN" not in denied.answer,
        "allowed: read": "PIN" in allowed.answer or "first school" in allowed.answer,
    }


SCENARIOS: dict[str, Callable[[Atlas, Fixtures, Callable[[Turn], None]], Result]] = {
    "invoices": invoices, "merge": merge, "maths": maths, "access": access,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenarios", nargs="*", default=list(SCENARIOS), help=f"of {list(SCENARIOS)}")
    parser.add_argument("--url", required=True, help="the Atlas to test, e.g. http://127.0.0.1:8001")
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()

    a = Atlas(args.url)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    logfile = ROOT / ".data" / "live" / f"{stamp}.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    # Outside Atlas's folder: Atlas's own files are on the policy's floor (the
    # agent may not write there), and the path stays short for Windows.
    fixture_root = Path(tempfile.gettempdir()) / "atlas-live"

    def log(turn: Turn) -> None:
        with logfile.open("a", encoding="utf-8") as fh:
            fh.write(turn.describe() + "\n")
        print(f"   {turn.label}: {turn.status}, {turn.seconds:.0f}s, tools: "
              f"{', '.join(t['name'] for t in turn.tools) or 'none'}", flush=True)

    original = a.settings()["access.folders"]
    summary: list[tuple[str, int, Result]] = []
    try:
        for name in args.scenarios:
            for trial in range(1, args.trials + 1):
                fx = build(fixture_root)
                a.put_settings({"access.folders": [str(fx.desktop)]})
                print(f"-- {name} #{trial}", flush=True)
                completed: list[bool] = []

                def log_and_check(turn: Turn, completed: list[bool] = completed) -> None:
                    completed.append(turn.status == "completed")
                    log(turn)

                result = {"every turn completed": True, **SCENARIOS[name](a, fx, log_and_check)}
                result["every turn completed"] = all(completed)
                summary.append((name, trial, result))
    finally:
        a.put_settings({"access.folders": original})

    lines = [f"\nLive checks {stamp} against {args.url}"]
    for name, trial, result in summary:
        passed = sum(result.values())
        lines.append(f"{name} #{trial}: {passed}/{len(result)}")
        lines += [f"    {'PASS' if ok else 'FAIL'}  {check}" for check, ok in result.items()]
    report = "\n".join(lines)
    print(report)
    with logfile.open("a", encoding="utf-8") as fh:
        fh.write(report + "\n")
    print(f"\nTrace: {logfile}")
    return 0 if all(all(r.values()) for _, _, r in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
