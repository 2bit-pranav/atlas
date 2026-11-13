"""The harder document tasks (tag `hard`): from the evaluation of 2026-11-12.

The suite's writing tasks passed 10/10 and were small. These five failed in 13
of 19 runs (benchmarks/2026-11-12-harder-documents). Their graders open the file
and check its structure: the evaluation's string matching passed a handbook
that held the reader's marks as text and no table.

The data comes from a fixed seed, so the files and what the graders expect
always agree, whether the files were made now or by an earlier run.
"""

from __future__ import annotations

import csv
import io
import random
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

VENDORS = ["Northwind Supply", "Corvex Ltd", "Brightline Tools", "Halden Freight", "Ostrava Paper", "Kestrel Labs",
           "Mirador Foods", "Tannery Row", "Quillon Print", "Verity Glass", "Umber & Co", "Solace Energy"]
SECTIONS = [("Water quality", "nitrate fell to 4.2 mg/L", "4.2"), ("Fish stocks", "trout counts rose to 1,340", "1340"),
            ("Bank erosion", "17 metres of bank were lost", "17"), ("Volunteer hours", "volunteers gave 2,615 hours", "2615"),
            ("Budget", "spending reached 48,900 euros", "48900"), ("Flood events", "there were 3 flood events", "3"),
            ("Invasive plants", "knotweed cover dropped to 11 percent", "11"), ("Next year", "the target is 9 new sites", "9")]
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
WORDS = "survey river channel record season station sample reading team site margin report level trend".split()


def _data() -> dict[str, Any]:
    """Every value the files hold and the graders expect, from one seed."""
    rng = random.Random(11)
    invoices = [(f"INV-{7301 + i}", v, f"2026-{9 + i % 2:02d}-{3 + 2 * i:02d}", round(rng.uniform(120, 9800), 2))
                for i, v in enumerate(VENDORS)]
    sales = {m: [(REGIONS[i % 4], f"rep{i:02d}", round(rng.uniform(200, 5000), 2)) for i in range(40)] for m in MONTHS}
    orders = [(f"O{1000 + i}", REGIONS[i % 4], rng.choice(["bolt", "gear", "seal", "valve"]), rng.randint(1, 40),
               round(rng.uniform(10, 900), 2)) for i in range(60)]
    totals = {f"{m}/{r}": round(sum(v for reg, _, v in sales[m] if reg == r), 2) for m in MONTHS for r in REGIONS}
    return {"invoices": invoices, "sales": sales, "orders": orders, "totals": totals,
            "invoice_total": round(sum(a for *_, a in invoices), 2),
            "north": [o for o in orders if o[1] == "North"],
            "north_total": round(sum(o[4] for o in orders if o[1] == "North"), 2)}


DATA = _data()
FILES = [*(f"{no.lower()}.pdf" for no, *_ in DATA["invoices"]), "review.pdf", "sales_q1.xlsx", "handbook.docx", "orders.csv"]


def _filler(rng: random.Random, n: int) -> str:
    return " ".join(" ".join(rng.choice(WORDS) for _ in range(12)).capitalize() + "." for _ in range(n))


def build(folder: Path) -> None:
    """The input files, each made only if missing."""
    if all((folder / f).exists() for f in FILES):
        return
    from docx import Document
    from openpyxl import Workbook
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(23)
    s = getSampleStyleSheet()
    for no, vendor, date, amount in DATA["invoices"]:
        SimpleDocTemplate(str(folder / f"{no.lower()}.pdf")).build([
            Paragraph("INVOICE", s["Title"]), Paragraph(f"From: {vendor}", s["BodyText"]),
            Paragraph(f"Invoice number: {no}", s["BodyText"]), Paragraph(f"Date: {date}", s["BodyText"]),
            Paragraph(_filler(rng, 3), s["BodyText"]), Paragraph(f"Subtotal: {amount * 0.82:,.2f}", s["BodyText"]),
            Paragraph(f"Tax: {amount * 0.18:,.2f}", s["BodyText"]), Paragraph(f"Amount due: {amount:,.2f}", s["BodyText"])])
    story = [Paragraph("Corvane River Annual Review 2026", s["Title"])]
    for title, fact, _key in SECTIONS:
        story += [Paragraph(title, s["Heading1"])] + [Paragraph(_filler(rng, 9), s["BodyText"]) for _ in range(5)]
        story += [Paragraph(f"In summary, {fact} this year.", s["BodyText"])]
        story += [Paragraph(_filler(rng, 9), s["BodyText"]) for _ in range(4)] + [PageBreak()]
    SimpleDocTemplate(str(folder / "review.pdf")).build(story)
    wb = Workbook()
    wb.remove(wb.active)
    for m in MONTHS:
        ws = wb.create_sheet(m)
        ws.append(["region", "rep", "revenue"])
        for row in DATA["sales"][m]:
            ws.append(list(row))
    wb.save(folder / "sales_q1.xlsx")
    doc = Document()
    doc.add_heading("Staff handbook draft", 0)
    doc.add_paragraph(_filler(rng, 6))
    doc.add_heading("Directory", 1)
    t = doc.add_table(rows=1, cols=4)
    for c, h in zip(t.rows[0].cells, ("Name", "Role", "City", "Joined"), strict=True):
        c.text = h
    for row in STAFF:
        for c, v in zip(t.add_row().cells, row, strict=True):
            c.text = v
    doc.add_heading("Leave policy", 1)
    doc.add_paragraph("Every employee gets 24 days of paid leave. " + _filler(rng, 4))
    doc.add_heading("Expenses", 1)
    doc.add_paragraph("Claims above 300 euros need a manager's sign-off. " + _filler(rng, 4))
    doc.save(str(folder / "handbook.docx"))
    (folder / "orders.csv").write_bytes(orders_csv())


def orders_csv() -> bytes:
    """orders.csv exactly as uploaded: the grader checks the upload was not changed."""
    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(["order_id", "region", "item", "qty", "amount"])
    w.writerows(DATA["orders"])
    return out.getvalue().encode("utf-8")


# ------------------------------------------------------------- reading ---

def _num(value: Any) -> float | None:
    """A cell or a piece of text as a number: 1,234.50 and "1234.5" alike."""
    if isinstance(value, int | float):
        return float(value)
    m = re.fullmatch(r"\s*[^\d\-]*(-?[\d,]*\.?\d+)\s*%?\s*", str(value or ""))
    try:
        return float(m.group(1).replace(",", "")) if m else None
    except ValueError:
        return None


def _near(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) < 0.006


def _workbook(path: Path | None) -> list[list[Any]] | None:
    """Every row of every sheet, or None when the file is missing or does not open as a workbook."""
    if path is None:
        return None
    try:
        from openpyxl import load_workbook

        book = load_workbook(str(path), data_only=True)
    except Exception:  # noqa: BLE001 - a file that does not open is a result
        return None
    return [list(r) for ws in book.worksheets for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]


def _document(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        from docx import Document

        return Document(str(path))
    except Exception:  # noqa: BLE001
        return None


def _marks(text: str) -> bool:
    """The reader's addresses left in a document as text."""
    return bool(re.search(r"\[b\d+\]|\[t\d+:|^r\d+:", text, re.M))


# ------------------------------------------------------------- graders ---
# Each takes the suite's Run and returns {fact: bool}; `suite.result` wraps them.

def g_invoices(run: Any) -> dict[str, bool]:
    rows = _workbook(run.workspace / "invoices.xlsx")
    if rows is None:
        return {"invoices.xlsx opens as a workbook": False}
    facts = {"invoices.xlsx opens as a workbook": True}
    for no, vendor, _date, amount in DATA["invoices"]:
        # One row holds the invoice's number, vendor and amount: not merely somewhere in the file.
        facts[f"{no} row"] = any(any(str(c).strip() == no for c in r) and any(vendor.lower() == str(c).strip().lower()
                                 for c in r) and any(_near(_num(c), amount) for c in r) for r in rows)
    total = DATA["invoice_total"]
    in_answer = any(_near(_num(m), total) for m in re.findall(r"\d[\d,]*\.\d{2}", run.answer))
    facts["total right (sheet or answer)"] = in_answer or any(_near(_num(c), total) for r in rows for c in r)
    return facts


def g_review(run: Any) -> dict[str, bool]:
    doc = _document(run.workspace / "summary.docx")
    if doc is None:
        return {"summary.docx opens": False}
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs).replace(",", "")
    facts = {"summary.docx opens": True, "one page (under 3,500 characters)": len(text) < 3500,
             "no reader marks": not _marks(text)}
    for title, _fact, key in SECTIONS:
        facts[f"{title}: {key}"] = any(re.search(rf"(?<![\d.]){re.escape(key)}(?![\d])", p.replace(",", ""))
                                       for p in paragraphs)
    return facts


def g_sales(run: Any) -> dict[str, bool]:
    doc = _document(run.workspace / "q1_report.docx")
    if doc is None:
        return {"q1_report.docx opens": False}
    facts = {"q1_report.docx opens": True, "has a table": bool(doc.tables)}
    rows = [[c.text.strip() for c in r.cells] for t in doc.tables for r in t.rows]
    for (key, value) in DATA["totals"].items():
        month, region = key.split("/")
        # In the row of its region (or the row of its month, if the table is the other way round).
        facts[key] = any(any(_near(_num(c), value) for c in r) and (region in r or month in r) for r in rows)
    return facts


def g_handbook(run: Any) -> dict[str, bool]:
    doc = _document(run.workspace / "handbook_v2.docx")
    if doc is None:
        return {"handbook_v2.docx opens": False}
    text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])
    headings = [p.text.strip() for p in doc.paragraphs if p.style is not None and p.style.name.startswith(("Heading", "Title"))]
    order = [h for h in headings if h in ("Leave policy", "Expenses")] or \
            [line.strip("# ").strip() for line in text.splitlines() if line.strip("# ").strip() in ("Leave policy", "Expenses")]
    table = [[c.text.strip() for c in r.cells] for r in doc.tables[0].rows] if doc.tables else []
    return {"handbook_v2.docx opens": True, "no reader marks": not _marks(text),
            "the Directory is one real table": len(doc.tables) == 1,
            "the table is exactly the original": table == [["Name", "Role", "City", "Joined"], *map(list, STAFF)],
            "Expenses before Leave policy": order[:2] == ["Expenses", "Leave policy"],
            "24 days kept": "24 days" in text, "300 euros kept": "300 euros" in text}


def g_orders(run: Any) -> dict[str, bool]:
    upload = run.workspace / "orders.csv"
    rows = _workbook(run.workspace / "north.xlsx")
    facts = {"orders.csv left unchanged": upload.exists() and upload.read_bytes() == orders_csv()}
    if rows is None:
        return {**facts, "north.xlsx opens as a workbook": False}
    ids = {str(c).strip() for r in rows for c in r if re.fullmatch(r"O1\d{3}", str(c).strip())}
    want = {o[0] for o in DATA["north"]}
    return {**facts, "north.xlsx opens as a workbook": True, "all North orders": want <= ids,
            "no other region's orders": ids <= want,
            "a last row with the total": any(_near(_num(c), DATA["north_total"]) for c in rows[-1])}


#: (name, tags, prompt, grader, uploads), in the suite's order.
TASKS: list[tuple[str, tuple[str, ...], str, Callable[[Any], dict[str, bool]], tuple[str, ...]]] = [
    ("hard-invoices", ("docs", "write", "hard"),
     "Make invoices.xlsx from these 12 invoices: one row each with invoice number, vendor, date and amount due, "
     "and tell me the total of all amounts due.", g_invoices, tuple(f"{no.lower()}.pdf" for no, *_ in DATA["invoices"])),
    ("hard-summary", ("docs", "write", "hard"),
     "Write summary.docx: a one-page summary of this review with one bullet per section, each giving that "
     "section's key figure.", g_review, ("review.pdf",)),
    ("hard-sales", ("docs", "write", "hard", "xlsx"),
     "Write q1_report.docx with a table of total revenue per region for each month (Jan, Feb, Mar), from this "
     "workbook.", g_sales, ("sales_q1.xlsx",)),
    ("hard-handbook", ("docs", "write", "hard"),
     "Make handbook_v2.docx from this document: keep the Directory table exactly, but put the Expenses section "
     "before the Leave policy section.", g_handbook, ("handbook.docx",)),
    ("hard-orders", ("docs", "write", "hard"),
     "From orders.csv make north.xlsx with only the North region's orders and a last row with the total amount.",
     g_orders, ("orders.csv",)),
]
