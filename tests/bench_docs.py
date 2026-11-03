"""The document benchmark: questions and edits on attached files, end to end.

    python tests/bench_docs.py --url http://127.0.0.1:8000
    python tests/bench_docs.py --ingest           # time ingest of the fixtures, no model

Baseline for docs/plan.md (file ingestion and retrieval). Same runner as
`bench.py`; fixtures are generated into `.data/bench/fixtures/` with one fact
planted in each, so every check is a string a script can find. Besides
pass/fail it counts what the plan is meant to reduce: wrong-tool calls (the
harness `read` on a binary document, refused by the policy), failed tool
calls, model calls and seconds.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench import FIXTURES, Case, Run, make_fixtures, run_case, trace  # noqa: E402

FONT = "C:/Windows/Fonts/arial.ttf"
WORDS = ("signal network sensor module report value system process data field level output input "
         "measure control unit stage test sample range method result device average period load").split()


def _filler(rng: random.Random, sentences: int) -> str:
    out = []
    for _ in range(sentences):
        w = rng.sample(WORDS, rng.randint(8, 14))
        out.append(" ".join(w).capitalize() + ".")
    return " ".join(out)


def make_doc_fixtures() -> None:
    make_fixtures()
    rng = random.Random(7)
    long_pdf = FIXTURES / "manual.pdf"          # 40 text pages; K7 constant on page 27
    if not long_pdf.exists():
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

        s = getSampleStyleSheet()
        story: list[Any] = []
        for page in range(1, 41):
            story.append(Paragraph(f"Section {page}: Sensor module {page}", s["Heading2"]))
            for _ in range(5):
                story.append(Paragraph(_filler(rng, 6), s["BodyText"]))
            if page == 27:
                story.append(Paragraph("The calibration constant for sensor K7 is 4.183 volts per unit.",
                                       s["BodyText"]))
            story.append(PageBreak())
        SimpleDocTemplate(str(long_pdf), pagesize=A4).build(story)

    scan = FIXTURES / "scan.pdf"                # 12 image-only pages; invoice number on page 9
    if not scan.exists():
        from PIL import Image, ImageDraw, ImageFont

        font = ImageFont.truetype(FONT, 30)
        pages = []
        for page in range(1, 13):
            img = Image.new("RGB", (1240, 1754), "white")
            d = ImageDraw.Draw(img)
            y = 120
            d.text((100, y), f"Delivery record page {page}", fill="black", font=font)
            for _ in range(14):
                y += 70
                line = " ".join(rng.sample(WORDS, 7))
                d.text((100, y), line, fill="black", font=font)
            if page == 9:
                d.text((100, y + 90), "Invoice number: INV-58213", fill="black", font=font)
            pages.append(img)
        pages[0].save(scan, save_all=True, append_images=pages[1:], resolution=150)

    docx = FIXTURES / "suppliers.docx"          # a table; Brightline lead time 23 days
    if not docx.exists():
        from docx import Document

        doc = Document()
        doc.add_heading("Supplier review", 0)
        for h in ("Background", "Method", "Findings"):
            doc.add_heading(h, 1)
            for _ in range(3):
                doc.add_paragraph(_filler(rng, 5))
        t = doc.add_table(rows=1, cols=3)
        t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = (
            "Supplier", "Unit price", "Lead time")
        for name, price, lead in (("Northwind", "12.40", "14 days"), ("Brightline", "9.85", "23 days"),
                                  ("Corvex", "15.10", "9 days")):
            r = t.add_row().cells
            r[0].text, r[1].text, r[2].text = name, price, lead
        doc.add_heading("Recommendation", 1)
        doc.add_paragraph("Keep Northwind as the main supplier and review Corvex next quarter.")
        doc.save(str(docx))

    text = FIXTURES / "server.log"              # 3000 lines; the error code on line 2417
    if not text.exists():
        lines = [f"2026-10-{1 + i // 120:02d} INFO worker-{i % 7} handled request {i} in {rng.randint(3, 90)} ms"
                 for i in range(3000)]
        lines[2416] = "2026-10-21 ERROR worker-3 disk quota exceeded (code E-7731)"
        text.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _has(run: Run, *needles: str) -> bool:
    a = run.answer.replace(",", "").lower()
    return all(n.lower() in a for n in needles)


def _docx_text(path: Path) -> str:
    from docx import Document

    d = Document(str(path))
    cells = [c.text for t in d.tables for row in t.rows for c in row.cells]
    return "\n".join([p.text for p in d.paragraphs] + cells)


def check_docx_edit(run: Run) -> dict[str, bool]:
    out = sorted(run.workspace.glob("*.docx"), key=lambda p: p.stat().st_mtime)
    try:
        text = _docx_text(out[-1]) if out else ""
    except Exception:  # noqa: BLE001 - a corrupt file is a failed edit
        text = ""
    return {"18 days present": "18 days" in text, "23 days gone": "23 days" not in text,
            # An edit, not a rewrite: everything else is still there.
            "rest unchanged": all(k in text for k in ("Northwind", "12.40", "14 days", "Corvex", "9 days",
                                                      "Keep Northwind as the main supplier"))}


def check_xlsx_edit(run: Run) -> dict[str, bool]:
    from openpyxl import load_workbook

    out = sorted(run.workspace.glob("*.xlsx"), key=lambda p: p.stat().st_mtime)
    if not out:
        return {"workbook present": False}
    try:
        wb = load_workbook(str(out[-1]))
    except Exception:  # noqa: BLE001 - a corrupt file is a failed edit
        return {"workbook opens": False}
    cells = {(ws.title, c.coordinate): c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row}
    expected = {("Jan", "B2"): 1200, ("Jan", "B3"): 3400.5, ("Jan", "B4"): 980, ("Feb", "B2"): 2200,
                ("Feb", "B3"): 1850.25, ("Feb", "B4"): 3100, ("Mar", "B3"): 2950.25, ("Mar", "B4"): 5400}
    return {"Mar North = 5000": cells.get(("Mar", "B2")) in (5000, 5000.0, "5000"),
            # An edit, not a rewrite: a regenerated workbook got Feb wrong (2026-11-03).
            "rest unchanged": all(cells.get(k) == v for k, v in expected.items())}


CASES = {c.name: c for c in [
    Case("pdf-long", "What is the calibration constant for sensor K7 in this manual?",
         uploads=["manual.pdf"], checks=lambda r: {"4.183": _has(r, "4.183")}),
    Case("pdf-scan", "What is the invoice number in this scanned document?",
         uploads=["scan.pdf"], checks=lambda r: {"INV-58213": _has(r, "58213")}),
    Case("pdf-short", "What apparatus does this experiment require?", uploads=["exp4.pdf"],
         checks=lambda r: {"Packet Tracer": _has(r, "packet tracer")}),
    Case("docx-table", "What is Brightline's lead time and unit price?", uploads=["suppliers.docx"],
         checks=lambda r: {"23 days": _has(r, "23"), "9.85": _has(r, "9.85")}),
    Case("xlsx-sum", "What is the total revenue for March in this workbook?", uploads=["sales.xlsx"],
         checks=lambda r: {"12450.75": _has(r, "12450.75")}),
    Case("text-long", "Which error code appears in this log, and on which worker?", uploads=["server.log"],
         checks=lambda r: {"E-7731": _has(r, "7731"), "worker-3": _has(r, "worker-3")}),
    Case("docx-edit", "In this document, change Brightline's lead time from 23 days to 18 days.",
         uploads=["suppliers.docx"], checks=check_docx_edit),
    Case("xlsx-edit", "In the Mar sheet of this workbook, set North's revenue to 5000.",
         uploads=["sales.xlsx"], checks=check_xlsx_edit),
]}

REFUSED = ("only handles text files", "would corrupt it", "is not a text file", "is an image")


def wrong_tool_calls(run: Run) -> int:
    return sum(1 for t in run.tools() if any(r in t["text"] for r in REFUSED))


def time_ingest() -> None:
    """Ingest of each fixture into a fresh store (no model): text pass, then OCR."""
    import tempfile

    from agent.ingest.store import Store

    store = Store(Path(tempfile.mkdtemp()) / "parsed")
    for name in ("manual.pdf", "suppliers.docx", "sales.xlsx", "exp1.pdf", "scan.pdf"):
        t = time.perf_counter()
        sha = store.submit(FIXTURES / name, "bench")
        assert sha
        first = store.wait(sha, lambda e: e["status"] != "queued", 120)
        t1 = time.perf_counter() - t
        if name == "scan.pdf":
            store.want(sha, [9])
            store.wait(sha, lambda e: e["page_status"][8] not in ("scan", "pictures"), 120)
            print(f"{name:<15} text pass {t1:5.2f}s  page 9 by OCR {time.perf_counter() - t:5.2f}s")
        done = store.wait(sha, lambda e: e["status"] == "ready", 300)
        print(f"{name:<15} {(first or {}).get('status')!s:<8} {t1:5.2f}s  ready {time.perf_counter() - t:6.2f}s  "
              f"blocks {len(store.blocks(sha))}  ({(done or {}).get('status')})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cases", nargs="*", default=list(CASES), help=f"of {list(CASES)}")
    parser.add_argument("--thinking", choices=["off", "on", "both"], default="both")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--ingest", action="store_true", help="time ingest of the fixtures only")
    args = parser.parse_args()

    make_doc_fixtures()
    if args.ingest:
        time_ingest()
        return 0
    client = httpx.Client(base_url=f"{args.url}/api", timeout=1800)
    settings = client.get("/settings").json()
    data_dir = Path(settings["paths"]["data"])
    out = data_dir / "bench" / ("docs-" + time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    modes = {"off": [False], "on": [True], "both": [False, True]}[args.thinking]

    results = []
    for name in args.cases:
        for thinking in modes:
            run, summary = run_case(client, CASES[name], thinking, data_dir)
            summary["wrong_tool"] = wrong_tool_calls(run)
            (out / f"{name}-think{int(thinking)}.md").write_text(trace(run, summary), encoding="utf-8")
            results.append(summary)
            mark = {True: "PASS", False: "FAIL", None: "----"}[summary["passed"]]
            failed = [k for k, v in summary["checks"].items() if not v]
            print(f"{mark} {name:<11} think={'on ' if thinking else 'off'} {summary['seconds']:>6}s "
                  f"calls={summary['model_calls']} ctx={summary['context']} tools={len(summary['tools'])} "
                  f"failed={summary['failed_tools']} wrong_tool={summary['wrong_tool']}"
                  + (f"  missing: {failed}" if failed else ""), flush=True)
    (out / "summary.json").write_text(json.dumps({"settings": settings["values"], "results": results},
                                                 indent=1, default=str), encoding="utf-8")
    print(f"\n{sum(1 for r in results if r['passed'])}/{len(results)} passed. Traces: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
