"""Fixtures for the live checks, generated so every machine gets the same files.

    <root>/Desktop/Demo/Invoices/invoice-0N-*.pdf   five text invoices, known total
    <root>/Desktop/Demo/Reports/                    empty (outputs go here)
    <root>/Desktop/Demo/Assignment/assignment-part1.pdf, -part2.pdf  (an image each; part 1 has a name)
    <root>/private/notes.txt                        outside the allowed folder

`<root>/Desktop` plays the user's allowed folder. Rebuilt from scratch on each
call, so an output left by an earlier run never changes the next one.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

#: vendor, file stem, date, items [(description, qty, rate)], GST %
INVOICES = [
    ("Annapurna Mess", "annapurna-mess", "01 Oct 2026", [("Monthly plan, lunch and dinner", 1, 4200.0),
                                                         ("Sunday special", 4, 60.0)], 0),
    ("SkyNet Fibre", "skynet-fibre", "05 Oct 2026", [("Student 100 Mbps, monthly rental", 1, 699.0)], 18),
    ("Bookworm Stationers", "bookworm-stationers", "09 Oct 2026", [("Operating System Concepts", 1, 875.0),
                                                                   ("Long notebook, 200 pages", 4, 65.0)], 0),
    ("QuickFix Laptop Care", "quickfix-laptop", "17 Oct 2026", [("Keyboard replacement", 1, 1850.0),
                                                                ("Labour", 1, 400.0)], 18),
    ("FitZone Gym", "fitzone-gym", "22 Oct 2026", [("Student membership, 3 months", 1, 2999.0)], 18),
]


@dataclass
class Fixtures:
    root: Path
    desktop: Path
    invoices: Path
    reports: Path
    assignment: Path
    notes: Path
    totals: dict[str, float]

    @property
    def total(self) -> float:
        return round(sum(self.totals.values()), 2)

    @property
    def top_vendor(self) -> str:
        return max(self.totals, key=self.totals.__getitem__)


def _invoice(path: Path, vendor: str, date: str, items: list[tuple[str, int, float]], gst: int) -> float:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 40, 90, 80), color=None, fill=(0.2, 0.4, 0.8))  # a logo mark, no letters
    page.insert_text((100, 62), vendor, fontsize=17)
    page.insert_text((420, 62), "TAX INVOICE", fontsize=13)
    page.insert_text((50, 120), "Billed to: Pranav Chandak, Room 214, Boys Hostel B, Pune 411037", fontsize=10)
    page.insert_text((50, 136), f"Invoice date: {date}", fontsize=10)
    y = 180
    for header, x in (("Description", 50), ("Qty", 330), ("Rate", 400), ("Amount (Rs.)", 470)):
        page.insert_text((x, y), header, fontsize=10)
    subtotal = 0.0
    for desc, qty, rate in items:
        y += 20
        subtotal += qty * rate
        for text, x in ((desc, 50), (str(qty), 330), (f"{rate:,.2f}", 400), (f"{qty * rate:,.2f}", 470)):
            page.insert_text((x, y), text, fontsize=10)
    tax = round(subtotal * gst / 100, 2)
    total = round(subtotal + tax, 2)
    for label, value in (("Sub-total", subtotal), (f"GST {gst}%", tax)):
        y += 22
        page.insert_text((360, y), label, fontsize=10)
        page.insert_text((470, y), f"{value:,.2f}", fontsize=10)
    page.insert_text((360, y + 26), "Total due", fontsize=12)
    page.insert_text((470, y + 26), f"Rs. {total:,.2f}", fontsize=12)
    doc.save(path)
    return total


def _picture(path: Path, bars: list[int], color: str) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (480, 300), "white")
    d = ImageDraw.Draw(img)
    for i, h in enumerate(bars):
        d.rectangle([40 + i * 80, 280 - h, 90 + i * 80, 280], fill=color)
    img.save(path)


def _assignment(path: Path, part: int, image: Path, text: str, name: bool) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), f"Data Structures - Assignment 3, Part {part}", fontsize=16)
    if name:
        page.insert_text((50, 82), "Submitted by: Pranav Chandak  |  Roll no 21CS045", fontsize=11)
    page.insert_textbox(fitz.Rect(50, 110, 545, 200), text, fontsize=11)
    page.insert_image(fitz.Rect(80, 210, 480, 460), filename=str(image))
    doc.save(path)


def build(root: Path) -> Fixtures:
    """Create (or reset) the fixtures under `root`."""
    desktop = root / "Desktop"
    if desktop.exists():
        shutil.rmtree(desktop)
    invoices, reports, assignment = (desktop / "Demo" / n for n in ("Invoices", "Reports", "Assignment"))
    for folder in (invoices, reports, assignment):
        folder.mkdir(parents=True)
    totals = {}
    for n, (vendor, stem, date, items, gst) in enumerate(INVOICES, 1):
        totals[vendor] = _invoice(invoices / f"invoice-{n:02d}-{stem}.pdf", vendor, date, items, gst)
    images = root / ".images"
    images.mkdir(exist_ok=True)
    _picture(images / "fig1.png", [60, 140, 220, 110, 180], "#2563eb")
    _picture(images / "fig2.png", [200, 90, 40, 160, 70], "#16a34a")
    _assignment(assignment / "assignment-part1.pdf", 1, images / "fig1.png",
                "This assignment compares arrays, linked lists and hash tables on insertion time, "
                "using 100,000 random keys. The figure shows the median of five runs.", name=True)
    _assignment(assignment / "assignment-part2.pdf", 2, images / "fig2.png",
                "Hash tables gave the fastest lookups; linked lists were slowest, because every search "
                "walks the list from the start.", name=False)
    private = root / "private"
    private.mkdir(exist_ok=True)
    notes = private / "notes.txt"
    notes.write_text("Bank PIN hint: my first school's name.\nDo not share this file.\n", encoding="utf-8")
    return Fixtures(root, desktop, invoices, reports, assignment, notes, totals)
