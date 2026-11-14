"""The pipelines (agent/tools/pipelines.py): code loops and checks, the model answers one question at a time.

The model is a script here. What is tested is what code guarantees whatever the
model says: a value not in its file is never kept, totals are added by code,
every section of a long PDF is reached, every change is found.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "live"))
import harder  # noqa: E402

from agent.ingest import parse  # noqa: E402
from agent.tools.pipelines import changes, describe, extract, numbers_grounded, sections, summarise  # noqa: E402


class Script:
    """A stand-in for ModelCall: `answer(prompt)` gives each reply."""

    def __init__(self, answer) -> None:
        self.answer, self.prompts = answer, []

    def ask(self, prompt, schema, **kw):
        self.prompts.append(prompt)
        return self.answer(prompt)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("inputs")
    harder.build(folder)
    return folder


def _pdf_blocks(path: Path) -> list[dict]:
    doc, out = parse.pdf_open(path), []
    for i in range(len(doc)):
        out += parse.pdf_page(doc, i, "x", Path(tempfile.mkdtemp()), [0])[1]
    return out


def test_a_table_from_twelve_invoices_keeps_only_values_in_each_file(inputs) -> None:
    files = [(f"{no.lower()}.pdf", _pdf_blocks(inputs / f"{no.lower()}.pdf")) for no, *_ in harder.DATA["invoices"]]

    def read(prompt):   # a good model, except that it invents the vendor of one invoice
        vendor = re.search(r"From: (.+)", prompt)[1].strip()
        return {"number": re.search(r"Invoice number: (\S+)", prompt)[1], "vendor": "Acme" if "INV-7305" in prompt else vendor,
                "amount due": re.search(r"Amount due: ([\d,.]+)", prompt)[1]}

    made = extract(Script(read), files, ["number", "vendor", "amount due"], total="amount due")
    assert len(made["rows"]) == 12 and made["rows"][0][1] == "INV-7301"
    assert made["rows"][4][2] == "" and any("Acme" in f for f in made["flagged"])          # invented: left empty
    assert float(made["total"]) == harder.DATA["invoice_total"]                            # added by code


def test_a_summary_reaches_every_section_and_checks_each_figure(inputs) -> None:
    parts = sections(_pdf_blocks(inputs / "review.pdf"))
    assert [t for t, _ in parts] == [t for t, _, _ in harder.SECTIONS]                     # all 16 pages, 8 sections
    asked: dict[str, int] = {}

    def point(prompt):
        title = prompt.split("\n", 1)[0].removeprefix("Section: ")
        asked[title] = asked.get(title, 0) + 1
        fact = dict((t, f) for t, f, _ in harder.SECTIONS)[title]
        if title == "Budget" and asked[title] == 1:
            return {"sentence": "Spending reached 52,000 euros.", "figure": "52,000 euros"}  # wrong first: asked again
        if title == "Next year":
            return {"sentence": "The target is 12 new sites.", "figure": ""}                # wrong twice: left out
        return {"sentence": f"In summary, {fact}.", "figure": ""}

    points, flagged = summarise(Script(point), parts)
    assert asked["Budget"] == 2 and ("Budget", "In summary, spending reached 48,900 euros.", "") in points
    assert [t for t, *_ in points] == [t for t, _, _ in harder.SECTIONS][:-1]
    assert flagged and flagged[0].startswith("Next year") and "12" in flagged[0]


def test_every_change_is_found_and_a_description_with_a_new_number_is_not_trusted() -> None:
    old = [{"kind": "heading", "text": "Terms"}, {"kind": "para", "text": "Payment is due in 30 days."},
           {"kind": "table", "text": "r1: Item | Price\nr2: Bolt | 4.00\nr3: Gear | 9.00"},
           {"kind": "para", "text": "Disputes go to arbitration."}]
    new = [{"kind": "heading", "text": "Terms"}, {"kind": "para", "text": "Payment is due in 45 days."},
           {"kind": "table", "text": "r1: Item | Price\nr2: Bolt | 4.50\nr3: Gear | 9.00"},
           {"kind": "para", "text": "Disputes go to arbitration."}, {"kind": "para", "text": "Either side may end it."}]
    found = changes(old, new)
    assert [(c["before"], c["after"]) for c in found] == [
        ("Payment is due in 30 days.", "Payment is due in 45 days."), ("r2: Bolt | 4.00", "r2: Bolt | 4.50"),
        ("", "Either side may end it.")]
    assert found[0]["where"] == "Terms"
    words = describe(Script(lambda p: {"change": "Payment terms went from 30 to 60 days."}), found[:1])
    assert words[0].startswith('Changed from "Payment is due in 30 days.')               # 60 is in neither version


def test_numbers_are_checked_loosely_but_not_invented() -> None:
    assert numbers_grounded("trout rose to 1,340 in 2026", "counts rose to 1340 this year (2026)") == []
    assert numbers_grounded("about 1,400 trout", "1,340 trout") == ["1,400"]


def test_the_policy_reads_every_input_and_creates_the_output(tmp_path, monkeypatch) -> None:
    from agent.safety.grid import effects
    from agent.safety.scope import Scope

    ws = tmp_path / "ws"
    ws.mkdir()
    scope = Scope(ws, folders=[])
    got = effects("extract_table", {"files": ["a.pdf", str(tmp_path / "Elsewhere")], "columns": ["x"],
                                    "path": "out.xlsx"}, None, scope)
    assert {(e.action, e.path) for e in got} == {("create", ws / "out.xlsx"), ("read", ws / "a.pdf"),
                                                 ("read", tmp_path / "Elsewhere")}
    got = effects("compare_documents", {"old": "v1.docx", "new": "v2.docx"}, None, scope)
    assert {(e.action, e.path.name) for e in got} == {("read", "v1.docx"), ("read", "v2.docx")}
