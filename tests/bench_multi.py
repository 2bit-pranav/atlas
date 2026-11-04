"""Multi-part tasks, two ways: one agent turn, or a plan plus workers.

    python tests/bench_multi.py --url http://127.0.0.1:8000 --repeats 3

Three tasks with facts planted in their inputs, so a script can grade
completeness (how many required facts the result has) and correctness (what
it got wrong): a three-source summary from pages on a local web server, a
two-file comparison, and a five-section report. Each runs in mode A (today's
agent) and mode B (the plan tool and the subagent tool switched on, and the
prompt asks to plan and hand each part to a worker). Model work is measured
from llama-server's own counters (`--metrics`), which include the workers'
calls; the turn's stats count the parent's only.

Needs: an Atlas whose llama-server runs with `--metrics` (and, for workers
that run side by side, two slots). The settings it changes are restored.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench import FIXTURES, Case, Run, run_case, trace  # noqa: E402

WEB = FIXTURES / "web"
WEB_PORT = 18090
PLAN = ("\n\nWork in steps: first write a plan with todo_write, one item per part. Then hand each "
        "part to a subagent with a clear, self-contained task (one subagent per {unit}). Then "
        "combine their results into the final answer yourself.")

# ------------------------------------------------------------- fixtures --

SOURCES = {
    "courier.html": ("Corvane Courier", "City council confirms river project",
                     ["The Corvane river cleanup began in March 2023.",
                      "The project is led by engineer Mira Okafor of the city water board.",
                      "The council approved a budget of 4.2 million for the work."]),
    "riverwatch.html": ("RiverWatch", "Volunteers pull waste from the Corvane",
                        ["Since the start, crews have removed 38 tonnes of waste from the riverbed.",
                         "About 120 volunteers join the cleanup every month.",
                         "RiverWatch puts the total budget at 4.6 million once the new pumps are counted."]),
    "halden.html": ("Halden University", "Water quality study, Corvane river",
                    ["Dissolved oxygen in the water has risen 18 percent since the cleanup began.",
                     "Seven fish species absent for a decade have returned, the study found.",
                     "Samples were taken at nine points along the river."]),
}

V1 = [("Parties", "This agreement is between Northwind Supply and Corvex Ltd."),
      ("Quantity", "The supplier delivers 5000 units each quarter."),
      ("Price", "The unit price is 12.40."),
      ("Payment", "Invoices are paid within 30 days."),
      ("Delivery", "Deliveries arrive every Monday."),
      ("Warranty", "Each unit carries a 12-month warranty."),
      ("Confidentiality", "Neither party discloses the terms of this agreement to third parties."),
      ("Termination", "Either party may end the agreement with 60 days' notice."),
      ("Governing law", "This agreement is governed by the laws of Ontario."),
      ("Contact", "Questions go to Dana Whitfield, account manager.")]
CHANGES = {"Price": "The unit price is 12.90.", "Payment": "Invoices are paid within 45 days.",
           "Delivery": "Deliveries arrive every Wednesday.", "Warranty": "Each unit carries a 24-month warranty.",
           "Termination": "Either party may end the agreement with 90 days' notice."}
V2 = [(h, CHANGES.get(h, t)) for h, t in V1 if h != "Confidentiality"]

NOTES = """Lumen app, project meeting notes, 3 April

- Priya opened: the Lumen app is the reading tracker for the library network.
- Beta goes to 40 library staff on May 2.
- Public launch is set for June 14, if the beta finds no blocking bugs.
- Budget so far: 18,500 approved, plus a 2,000 contingency held by finance.
- Tomas worried about a supplier delay on the barcode scanner kits.
- Second risk: only two engineers know the sync code; if one leaves, we slip.
- Agreed next step: Priya owns hiring a third engineer by May 20.
- Agreed next step: Tomas asks the scanner supplier for a firm date this week.
- Coffee machine on floor 2 is broken again (not a project item).
"""


def make_fixtures() -> None:
    WEB.mkdir(parents=True, exist_ok=True)
    for name, (site, title, paras) in SOURCES.items():
        body = "".join(f"<p>{p}</p>" for p in paras)
        (WEB / name).write_text(f"<html><head><title>{title} - {site}</title></head><body><h1>{title}</h1>"
                                f"<p><em>Published by {site}</em></p>{body}</body></html>", encoding="utf-8")
    from docx import Document

    for name, clauses in (("supply_v1.docx", V1), ("supply_v2.docx", V2)):
        if (FIXTURES / name).exists():
            continue
        d = Document()
        d.add_heading("Supply agreement", 0)
        for heading, text in clauses:
            d.add_heading(heading, 1)
            d.add_paragraph(text)
        d.save(str(FIXTURES / name))
    (FIXTURES / "notes.txt").write_text(NOTES, encoding="utf-8")


def serve() -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", WEB_PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


# --------------------------------------------------------------- grading --

def _norm(text: str) -> str:
    return text.lower().replace(",", "").replace("**", "")


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", _norm(text)) if s.strip()]


def grade_research(run: Run) -> dict[str, Any]:
    # Links are not claims: 127.0.0.1:18090 in an echoed URL counted as three invented numbers.
    a = re.sub(r"https?://\S+", " ", _norm(run.answer))
    facts = {"started 2023": "2023" in a, "led by Okafor": "okafor" in a, "38 tonnes": "38" in a,
             "120 volunteers": "120" in a, "oxygen +18%": "18" in a,
             "7 species": bool(re.search(r"\b(7|seven)\b[^.]{0,40}species", a)),
             "both budgets": "4.2" in a and "4.6" in a}
    attributed = (any("4.2" in s and "courier" in s for s in _sentences(run.answer))
                  and any("4.6" in s and "riverwatch" in s for s in _sentences(run.answer)))
    known = {"2023", "4.2", "4.6", "38", "120", "18", "7", "9", "1", "2", "3", "10"}
    invented = sorted({n for n in re.findall(r"\b\d+(?:\.\d+)?\b", a)} - known)
    return {"facts": facts, "complete": sum(facts.values()), "of": len(facts),
            "errors": (0 if attributed else 1) + len(invented), "notes": {"budget attributed": attributed,
                                                                         "numbers in no source": invented}}


def grade_compare(run: Run) -> dict[str, Any]:
    a = _norm(run.answer)
    found = {"price 12.40->12.90": "12.4" in a and "12.9" in a,
             "payment 30->45": bool(re.search(r"\b30\b", a)) and bool(re.search(r"\b45\b", a)),
             "Monday->Wednesday": "monday" in a and "wednesday" in a,
             "warranty 12->24": bool(re.search(r"\b24\b", a)) and "warrant" in a,
             "notice 60->90": bool(re.search(r"\b60\b", a)) and bool(re.search(r"\b90\b", a)),
             "confidentiality removed": "confidential" in a and bool(re.search(r"remov|missing|delet|dropp|no longer|absent|not in|omit", a))}
    change = re.compile(r"chang|differ|updat|increas|decreas|now |instead|replac|from .* to ")
    decoys = {"quantity 5000": "5000", "Ontario": "ontario", "Dana Whitfield": "whitfield", "parties": "northwind"}
    false = sorted(k for k, word in decoys.items()
                   if any(word in s and change.search(s) for s in _sentences(run.answer)))
    return {"facts": found, "complete": sum(found.values()), "of": len(found), "errors": len(false),
            "notes": {"unchanged items called changed": false}}


SECTIONS = {"summary": ["lumen"], "timeline": ["may 2", "june 14"], "budget": ["18500", "2000"],
            "risks": ["supplier", "two engineers"], "next steps": ["priya", "hir"]}


def grade_draft(run: Run) -> dict[str, Any]:
    out = sorted(run.workspace.glob("*.docx"), key=lambda p: p.stat().st_mtime)
    if not out:
        return {"facts": {"document created": False}, "complete": 0, "of": 1 + 5 + 10, "errors": 1, "notes": {}}
    try:
        from docx import Document

        doc = Document(str(out[-1]))
    except Exception:  # noqa: BLE001 - a corrupt file is an error
        return {"facts": {"document opens": False}, "complete": 0, "of": 16, "errors": 1, "notes": {}}
    current, body = None, {}
    for p in doc.paragraphs:
        text = _norm(p.text).strip()
        key = next((k for k in SECTIONS if text.strip("# :0123456789.") == k), None)
        if key and (p.style.name.startswith(("Heading", "Title")) or len(text) < 25):
            current = key
            body.setdefault(key, "")
        elif current:
            body[current] += " " + text
    for t in doc.tables:
        if current:
            body[current] += " " + " ".join(_norm(c.text) for r in t.rows for c in r.cells)
    whole = " ".join(body.values()) + " ".join(_norm(p.text) for p in doc.paragraphs)
    facts: dict[str, bool] = {"document created": True}
    facts.update({f"section {k}": k in body for k in SECTIONS})
    misplaced = []
    for k, needles in SECTIONS.items():
        for n in needles:
            facts[f"{k}: {n}"] = n in whole
            if n in whole and k in body and n not in body[k]:
                misplaced.append(f"{n} not under {k}")
    off_topic = "coffee" in whole
    return {"facts": facts, "complete": sum(facts.values()), "of": len(facts),
            "errors": len(misplaced) + int(off_topic), "notes": {"misplaced": misplaced, "off-topic item kept": off_topic}}


def _url(name: str) -> str:
    return f"http://127.0.0.1:{WEB_PORT}/{name}"


TASKS = {
    "research": (("Read these three pages and write a summary of the Corvane river cleanup: when it started, "
                  "who leads it, the budget, how much waste was removed, how many volunteers take part, and "
                  "what it has done for the river. Where the sources disagree, say so and name which source "
                  f"says what. Pages: {_url('courier.html')} {_url('riverwatch.html')} {_url('halden.html')}"),
                 [], "source", grade_research),
    "compare": ("Compare supply_v1.docx and supply_v2.docx and list every difference between them, with the "
                "old and the new wording.", ["supply_v1.docx", "supply_v2.docx"], "file", grade_compare),
    "draft": ("Using notes.txt, write a Word report, report.docx, with exactly these sections: Summary, "
              "Timeline, Budget, Risks, Next steps. Put each fact from the notes under the section it belongs "
              "to, and leave out anything that is not about the project.", ["notes.txt"], "section", grade_draft),
}

MODES = {"A": {"tools.builtin.todos": False},
         "B": {"tools.builtin.todos": True}}


def metrics(llama: str, key: str | None) -> dict[str, float]:
    """llama-server's counters: prompt tokens read and tokens generated, all slots."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    text = httpx.get(f"{llama}/metrics", headers=headers, timeout=10).text
    out = {}
    for name in ("llamacpp:prompt_tokens_total", "llamacpp:tokens_predicted_total"):
        m = re.search(rf"^{re.escape(name)}\s+([0-9.e+]+)", text, re.M)
        out[name.split(":")[1]] = float(m[1]) if m else 0.0
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tasks", nargs="*", default=list(TASKS))
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--llama", default="http://127.0.0.1:8080")
    parser.add_argument("--llama-key", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--thinking", choices=["off", "on", "both"], default="both")
    args = parser.parse_args()

    make_fixtures()
    serve()
    client = httpx.Client(base_url=f"{args.url}/api", timeout=1800)
    settings = client.get("/settings").json()
    before = {k: settings["values"].get(k) for k in [*MODES["B"], "tools.builtin.web_fetch"]}
    data_dir = Path(settings["paths"]["data"])
    out = data_dir / "bench" / ("multi-" + time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    modes_thinking = {"off": [False], "on": [True], "both": [False, True]}[args.thinking]
    results = []
    try:
        client.put("/settings", json={"tools.builtin.web_fetch": True}).raise_for_status()
        for rep in range(args.repeats):
            for name in args.tasks:
                prompt, uploads, unit, grade = TASKS[name]
                for thinking in modes_thinking:
                    for mode in ("A", "B"):        # interleaved, so neither mode gets a warmer cache
                        client.put("/settings", json=MODES[mode]).raise_for_status()
                        text = prompt + (PLAN.format(unit=unit) if mode == "B" else "")
                        m0 = metrics(args.llama, args.llama_key)
                        run, summary = run_case(client, Case(f"{name}-{mode}", text, uploads), thinking, data_dir)
                        m1 = metrics(args.llama, args.llama_key)
                        g = grade(run)
                        summary.update({"task": name, "mode": mode, "rep": rep, "grade": g,
                                        "subagents": len(run.tools("subagent")), "plans": len(run.tools("todo_write")),
                                        "prompt_tokens": m1["prompt_tokens_total"] - m0["prompt_tokens_total"],
                                        "gen_tokens": m1["tokens_predicted_total"] - m0["tokens_predicted_total"]})
                        (out / f"{name}-{mode}-think{int(thinking)}-r{rep}.md").write_text(trace(run, summary), encoding="utf-8")
                        results.append(summary)
                        print(f"{name:<9} {mode} think={'on ' if thinking else 'off'} r{rep} "
                              f"complete {g['complete']}/{g['of']} errors {g['errors']} | {summary['seconds']:>6}s "
                              f"workers={summary['subagents']} plan={summary['plans']} status={summary['status']} "
                              f"tokens in/out {summary['prompt_tokens']:.0f}/{summary['gen_tokens']:.0f}", flush=True)
                        (out / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    finally:
        client.put("/settings", json={k: v for k, v in before.items() if v is not None})
    print(f"\nTraces and results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
