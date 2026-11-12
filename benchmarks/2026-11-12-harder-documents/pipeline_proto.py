"""Prototype of the proposed code-driven pipelines, on the same inputs the agent struggled with.

1. extract_table: one schema-constrained call per invoice, each value checked against the page text.
2. section_summary: one constrained call per section of the 16-page review, figure must appear in the text.

Talks to llama-server directly (as agent/extension/form_fill.py does). No agent loop, no tools.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil
import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).parent))
from stress_docs import INVOICES, SECTIONS  # noqa: E402

FIX = Path(tempfile.gettempdir()) / "atlas-stress-fixtures"
KEY = next(a[i + 1] for p in psutil.process_iter(["cmdline"]) if (a := p.info["cmdline"] or []) and "--api-key" in a
           for i, x in enumerate(a) if x == "--api-key")
LLAMA = httpx.Client(base_url="http://127.0.0.1:8080", headers={"Authorization": f"Bearer {KEY}"}, timeout=180)


def pages(path: Path) -> list[str]:
    doc = pdfium.PdfDocument(str(path))
    return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]


def ask(system: str, user: str, schema: dict, max_tokens: int = 300) -> tuple[dict, float, int]:
    t0 = time.time()
    r = LLAMA.post("/v1/chat/completions", json={
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}})
    r.raise_for_status()
    body = r.json()
    return json.loads(body["choices"][0]["message"]["content"]), time.time() - t0, body["usage"]["completion_tokens"]


def norm(s: str) -> str:
    return re.sub(r"[\s,]+", "", s).lower()


def grounded(value: str, text: str) -> bool:
    return bool(value.strip()) and norm(value) in norm(text)


# ------------------------------------------------------------ 1. extract_table

COLUMNS = ["invoice_number", "vendor", "date", "amount_due"]
ROW = {"type": "object", "additionalProperties": False, "required": COLUMNS,
       "properties": {c: {"type": "string", "maxLength": 80} for c in COLUMNS}}
SYS_ROW = ("You copy fields out of one document. For each field give the value exactly as it is written in the "
           'document. If the document does not say, give "". Never invent a value.')


def extract_one(path: Path) -> dict:
    text = "\n".join(pages(path))[:6000]
    row, secs, toks = ask(SYS_ROW, f"Document {path.name}:\n{text}\n\nFields: {', '.join(COLUMNS)}", ROW)
    flags = [c for c in COLUMNS if not grounded(row[c], text)]
    return {"file": path.name, "row": row, "ungrounded": flags, "secs": secs, "tokens": toks}


def extract_table(workers: int) -> None:
    files = [FIX / f"{no.lower()}.pdf" for no, *_ in INVOICES]
    t0 = time.time()
    with ThreadPoolExecutor(workers) as pool:
        out = list(pool.map(extract_one, files))
    wall = time.time() - t0
    right = flagged = 0
    for (no, vendor, date, amount), o in zip(INVOICES, out):
        r = o["row"]
        ok = [r["invoice_number"] == no, r["vendor"] == vendor, r["date"] == date,
              norm(r["amount_due"]) == norm(f"{amount:,.2f}")]
        right += sum(ok)
        flagged += len(o["ungrounded"])
        if not all(ok) or o["ungrounded"]:
            print("   MISS", o["file"], r, "expected", (no, vendor, date, f"{amount:,.2f}"), "ungrounded:", o["ungrounded"])
    total = sum(float(o["row"]["amount_due"].replace(",", "") or 0) for o in out)   # code adds, not the model
    print(f"[extract_table x{workers}] {right}/{4 * len(files)} fields right, {flagged} flagged by the grounding check, "
          f"total by code {total:,.2f} (truth {sum(a for *_, a in INVOICES):,.2f}); wall {wall:.1f}s, "
          f"{sum(o['tokens'] for o in out)} output tokens, {wall / len(files):.1f}s per file")


# --------------------------------------------------------- 2. section_summary

POINT = {"type": "object", "additionalProperties": False, "required": ["key_figure", "sentence"],
         "properties": {"key_figure": {"type": "string", "maxLength": 40}, "sentence": {"type": "string", "maxLength": 200}}}
SYS_POINT = ("You summarise one section of a report. Give its single most important figure exactly as written "
             "(the number with its unit), and one sentence that states it. Use only this section's text.")


def section_summary() -> None:
    text = pages(FIX / "review.pdf")
    # Each section is the text from its heading up to the next heading (what the ingest outline gives).
    joined = "\n".join(text)
    marks = [(joined.find("\n" + t), t) for t, _ in SECTIONS]
    marks = sorted((i, t) for i, t in marks if i >= 0) + [(len(joined), "")]
    t0 = time.time()
    bullets, hit, ungrounded, toks = [], 0, 0, 0
    for (start, title), (end, _) in zip(marks, marks[1:]):
        body = joined[start:end][:7000]
        out, _secs, n = ask(SYS_POINT, f"Section: {title}\n\n{body}", POINT, 150)
        toks += n
        fact = dict(SECTIONS)[title]
        key = [w for w in fact.replace(",", "").split() if any(ch.isdigit() for ch in w)][0]
        ok = key in out["key_figure"].replace(",", "") or key in out["sentence"].replace(",", "")
        hit += ok
        g = grounded(out["key_figure"], body)
        ungrounded += not g
        bullets.append(f"- **{title}:** {out['sentence']}")
        if not ok:
            print("   MISS", title, out, "expected", fact, "| grounded:", g)
    print(f"[section_summary] {hit}/{len(SECTIONS)} key figures right, {ungrounded} flagged ungrounded; "
          f"wall {time.time() - t0:.1f}s, {toks} output tokens")
    print("   " + "\n   ".join(bullets[:3]))


if __name__ == "__main__":
    for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 1):
        extract_table(1)
        section_summary()
