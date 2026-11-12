"""Harder document-creation tasks than the suite's, graded by script on planted facts.

    python stress_docs.py [task ...] [--thinking off|on|both] [--out DIR]

Each task: build inputs, upload to a fresh chat, one message, grade the file produced.
Traces (every step, args, results) are written to --out for reading failures.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
import time
from pathlib import Path

import httpx

URL = "http://127.0.0.1:8000/api"
FIX = Path(tempfile.gettempdir()) / "atlas-stress-fixtures"
rng = random.Random(11)

VENDORS = ["Northwind Supply", "Corvex Ltd", "Brightline Tools", "Halden Freight", "Ostrava Paper", "Kestrel Labs",
           "Mirador Foods", "Tannery Row", "Quillon Print", "Verity Glass", "Umber & Co", "Solace Energy"]
INVOICES = [(f"INV-{7301 + i}", v, f"2026-{9 + i % 2:02d}-{3 + 2 * i:02d}", round(rng.uniform(120, 9800), 2))
            for i, v in enumerate(VENDORS)]
SECTIONS = [("Water quality", "nitrate fell to 4.2 mg/L"), ("Fish stocks", "trout counts rose to 1,340"),
            ("Bank erosion", "17 metres of bank were lost"), ("Volunteer hours", "volunteers gave 2,615 hours"),
            ("Budget", "spending reached 48,900 euros"), ("Flood events", "there were 3 flood events"),
            ("Invasive plants", "knotweed cover dropped to 11 percent"), ("Next year", "the target is 9 new sites")]
REGIONS = ["North", "South", "East", "West"]
MONTHS = ["Jan", "Feb", "Mar"]
STAFF = [("Asha Verma", "Engineer", "Pune", "2019"), ("Liam Okoro", "Designer", "Leeds", "2021"),
         ("Mei Tanaka", "Analyst", "Osaka", "2018"), ("Ravi Menon", "Manager", "Kochi", "2015"),
         ("Sofia Ruiz", "Engineer", "Madrid", "2022"), ("Tomas Novak", "Support", "Brno", "2020"),
         ("Uma Pillai", "Analyst", "Chennai", "2017"), ("Viktor Lund", "Engineer", "Oslo", "2016"),
         ("Wen Li", "Designer", "Suzhou", "2023"), ("Yara Haddad", "Manager", "Amman", "2014"),
         ("Zane Carter", "Support", "Perth", "2021"), ("Bea Fontaine", "Engineer", "Lyon", "2019"),
         ("Cato Reyes", "Analyst", "Cebu", "2020"), ("Dara Singh", "Designer", "Delhi", "2018"),
         ("Elin Berg", "Engineer", "Umea", "2022")]


def filler(n: int) -> str:
    words = "survey river channel record season station sample reading team site margin report level trend".split()
    return " ".join(" ".join(rng.choice(words) for _ in range(12)).capitalize() + "." for _ in range(n))


def build() -> dict[str, float]:
    from docx import Document
    from openpyxl import Workbook
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

    FIX.mkdir(exist_ok=True)
    s = getSampleStyleSheet()
    for no, vendor, date, amount in INVOICES:
        SimpleDocTemplate(str(FIX / f"{no.lower()}.pdf")).build([
            Paragraph("INVOICE", s["Title"]), Paragraph(f"From: {vendor}", s["BodyText"]),
            Paragraph(f"Invoice number: {no}", s["BodyText"]), Paragraph(f"Date: {date}", s["BodyText"]),
            Paragraph(filler(3), s["BodyText"]), Paragraph(f"Subtotal: {amount * 0.82:,.2f}", s["BodyText"]),
            Paragraph(f"Tax: {amount * 0.18:,.2f}", s["BodyText"]),
            Paragraph(f"Amount due: {amount:,.2f}", s["BodyText"])])
    story = [Paragraph("Corvane River Annual Review 2026", s["Title"])]
    for title, fact in SECTIONS:
        story += [Paragraph(title, s["Heading1"])] + [Paragraph(filler(9), s["BodyText"]) for _ in range(5)]
        story += [Paragraph(f"In summary, {fact} this year.", s["BodyText"])]
        story += [Paragraph(filler(9), s["BodyText"]) for _ in range(4)] + [PageBreak()]
    SimpleDocTemplate(str(FIX / "review.pdf")).build(story)
    wb = Workbook()
    wb.remove(wb.active)
    totals: dict[str, float] = {}
    for m in MONTHS:
        ws = wb.create_sheet(m)
        ws.append(["region", "rep", "revenue"])
        for i in range(40):
            region, rev = REGIONS[i % 4], round(rng.uniform(200, 5000), 2)
            ws.append([region, f"rep{i:02d}", rev])
            totals[f"{m}/{region}"] = round(totals.get(f"{m}/{region}", 0) + rev, 2)
    wb.save(FIX / "sales_q1.xlsx")
    doc = Document()
    doc.add_heading("Staff handbook draft", 0)
    doc.add_paragraph(filler(6))
    doc.add_heading("Directory", 1)
    t = doc.add_table(rows=1, cols=4)
    for c, h in zip(t.rows[0].cells, ("Name", "Role", "City", "Joined")):
        c.text = h
    for row in STAFF:
        for c, v in zip(t.add_row().cells, row):
            c.text = v
    doc.add_heading("Leave policy", 1)
    doc.add_paragraph("Every employee gets 24 days of paid leave. " + filler(4))
    doc.add_heading("Expenses", 1)
    doc.add_paragraph("Claims above 300 euros need a manager's sign-off. " + filler(4))
    doc.save(FIX / "handbook.docx")
    with (FIX / "orders.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["order_id", "region", "item", "qty", "amount"])
        north = 0.0
        for i in range(60):
            region, amt = REGIONS[i % 4], round(rng.uniform(10, 900), 2)
            north += amt if region == "North" else 0
            w.writerow([f"O{1000 + i}", region, rng.choice(["bolt", "gear", "seal", "valve"]), rng.randint(1, 40), amt])
    totals["north_orders"] = round(north, 2)
    return totals


# ------------------------------------------------------------- reading outputs --

def xlsx_text(path: Path) -> tuple[str, list[list]]:
    from openpyxl import load_workbook
    rows = [list(r) for ws in load_workbook(path, data_only=True) for r in ws.iter_rows(values_only=True)]
    return " ".join(str(c) for r in rows for c in r if c is not None), rows


def docx_text(path: Path) -> str:
    from docx import Document
    d = Document(str(path))
    cells = [c.text for t in d.tables for r in t.rows for c in r.cells]
    return "\n".join([p.text for p in d.paragraphs] + cells)


def nums(text: str) -> set[str]:
    import re
    return {f"{float(m.replace(',', '')):.2f}" for m in re.findall(r"\d[\d,]*\.?\d*", text) if m.strip(",.")}


def newest(ws: Path, suffix: str, since: float) -> Path | None:
    found = sorted((p for p in ws.rglob(f"*{suffix}") if p.stat().st_mtime >= since), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


# ---------------------------------------------------------------------- tasks --

def g_invoices(ws: Path, since: float, totals: dict, answer: str) -> dict:
    out = newest(ws, ".xlsx", since)
    if out is None:
        return {"file": False}
    text, rows = xlsx_text(out)
    got = nums(text)
    facts = {"file": True}
    for no, vendor, date, amount in INVOICES:
        facts[f"{no} amount"] = f"{amount:.2f}" in got
        facts[f"{no} vendor"] = vendor.lower() in text.lower()
        facts[f"{no} number"] = no in text
    facts["total"] = f"{sum(a for *_, a in INVOICES):.2f}" in got | nums(answer)
    return facts


def g_review(ws: Path, since: float, totals: dict, answer: str) -> dict:
    out = newest(ws, ".docx", since)
    if out is None:
        return {"file": False}
    text = docx_text(out).lower().replace(",", "")
    facts = {"file": True}
    for title, fact in SECTIONS:
        key = [w for w in fact.replace(",", "").split() if any(ch.isdigit() for ch in w)][0]
        facts[f"{title}: {key}"] = key in text
    return facts


def g_sales(ws: Path, since: float, totals: dict, answer: str) -> dict:
    out = newest(ws, ".docx", since)
    if out is None:
        return {"file": False}
    got = nums(docx_text(out))
    return {"file": True, **{k: f"{v:.2f}" in got for k, v in totals.items() if "/" in k}}


def g_handbook(ws: Path, since: float, totals: dict, answer: str) -> dict:
    out = newest(ws, ".docx", since)
    if out is None:
        return {"file": False}
    text = docx_text(out)
    facts = {"file": True, "24 days": "24 days" in text, "300 euros": "300" in text,
             "expenses before leave": 0 <= text.find("Expenses") < text.find("Leave policy")}
    for row in STAFF:
        facts[f"row {row[0]}"] = all(v in text for v in row)
    return facts


def g_orders(ws: Path, since: float, totals: dict, answer: str) -> dict:
    out = newest(ws, ".xlsx", since)
    if out is None:
        return {"file": False}
    text, rows = xlsx_text(out)
    ids = {str(c) for r in rows for c in r if isinstance(c, str) and c.startswith("O1")}
    want = {f"O{1000 + i}" for i in range(0, 60, 4)}
    return {"file": True, "all 15 North orders": want <= ids, "no other region's orders": ids <= want,
            "total row": f"{totals['north_orders']:.2f}" in nums(text)}


TASKS = {
    "invoices12": ([f"{no.lower()}.pdf" for no, *_ in INVOICES],
                   "Make invoices.xlsx from these 12 invoices: one row each with invoice number, vendor, date and "
                   "amount due, and tell me the total of all amounts due.", g_invoices),
    "review-summary": (["review.pdf"],
                       "Write summary.docx: a one-page summary of this review with one bullet per section, each "
                       "giving that section's key figure.", g_review),
    "sales-report": (["sales_q1.xlsx"],
                     "Write q1_report.docx with a table of total revenue per region for each month (Jan, Feb, Mar), "
                     "from this workbook.", g_sales),
    "handbook-reorder": (["handbook.docx"],
                         "Make handbook_v2.docx from this document: keep the Directory table exactly, but put the "
                         "Expenses section before the Leave policy section.", g_handbook),
    "orders-filter": (["orders.csv"],
                      "From orders.csv make north.xlsx with only the North region's orders and a last row with the "
                      "total amount.", g_orders),
}


def run(c: httpx.Client, name: str, thinking: bool, totals: dict, data: Path, out: Path) -> dict:
    uploads, prompt, grade = TASKS[name]
    cid = c.post("/chats", json={"title": f"[stress] {name}"}).json()["id"]
    files = [c.post(f"/chats/{cid}/files", files={"file": (n, (FIX / n).read_bytes())}).json() for n in uploads]
    since = time.time() - 1
    sent = c.post(f"/chats/{cid}/messages", json={"text": prompt, "files": files, "thinking": thinking})
    sent.raise_for_status()
    rid = sent.json()["run"]["id"]
    with c.stream("GET", f"/runs/{rid}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                e = json.loads(line[6:])
                if e["type"] == "approval_request":
                    c.post(f"/runs/{rid}/approvals/{e['id']}", json={"allow": True})
                if e["type"] in ("done", "error"):
                    break
    turn = c.get(f"/chats/{cid}").json()["turns"][-1]
    parts = turn.get("render") or []
    answer = "".join(p["text"] for p in parts if p["kind"] == "text")
    facts = grade(data / "chats" / cid, since, totals, answer)
    stats = turn.get("stats") or {}
    tools = [p for p in parts if p["kind"] == "tool"]
    summary = {"task": name, "thinking": thinking, "status": turn["status"], "ok": sum(facts.values()),
               "of": len(facts), "missed": [k for k, v in facts.items() if not v],
               "seconds": round(stats.get("duration_ms", 0) / 1000, 1), "model_calls": stats.get("model_calls"),
               "context": stats.get("context_used"), "completion_tokens": stats.get("completion_tokens"),
               "tools": [f"{p['name']}{'!' if p['status'] == 'error' else ''}" for p in tools], "chat": cid}
    lines = [f"# {name} thinking={thinking}", "```json", json.dumps(summary, indent=1), "```", ""]
    for i, p in enumerate(parts, 1):
        if p["kind"] == "tool":
            lines += [f"## {i}. tool {p['name']} -> {p['status']}", "```",
                      json.dumps(p["args"], ensure_ascii=False, indent=1)[:6000], "```", "result:", "```",
                      (p.get("text") or "")[:2500], "```"]
        else:
            lines += [f"## {i}. {p['kind']}", "```", (p.get("text") or json.dumps(p))[:3000], "```"]
    (out / f"{name}-{'on' if thinking else 'off'}-{cid[:6]}.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="*")
    ap.add_argument("--thinking", default="both")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", default=str(Path(__file__).parent / "stress-traces"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    totals = build()
    c = httpx.Client(base_url=URL, timeout=None)
    data = Path(c.get("/settings").json()["paths"]["data"])
    results = []
    for _ in range(a.repeats):
        for name in a.tasks or list(TASKS):
            for thinking in {"off": [False], "on": [True], "both": [False, True]}[a.thinking]:
                s = run(c, name, thinking, totals, data, out)
                results.append(s)
                print(f"{name:17} think={'on ' if thinking else 'off'} {s['status']:9} {s['ok']:>2}/{s['of']:<2} "
                      f"{s['seconds']:6.1f}s calls={s['model_calls']} ctx={s['context']} out_tok={s['completion_tokens']} "
                      f"tools={','.join(s['tools'])[:150]}\n    missed: {s['missed'][:8]}", flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
