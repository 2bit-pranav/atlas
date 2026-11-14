"""Document work done by code, the model asked one small question at a time (plan 3.3-3.5).

The agent was slow and often wrong at three shapes of task (2026-11-12): a table
from many files (it retyped values, 84-112 s), a summary of a long document (it
read page 1 of 16), and a comparison of two versions. Here code does the loop:

- `extract_table`: one question per file ("these columns, copied as written"),
  each value checked against that file's text, totals added by code (Decimal).
  The prototype: 48/48 fields, 11 s.
- `write_summary`: the document cut into its sections, one question per section
  (one sentence and its key figure), every number checked against that section.
  The prototype: 8/8 figures.
- `compare_documents`: code lines the versions up and finds what changed; the
  model only words each change, and its numbers must be in the old or new text.

A value that fails its check is left out and named in the result, never kept.
Every question goes through `ModelCall` (Stop, the run's limits, the trace).
The files are read through the ingest store, as the read tools read them, and
the tool policy checks them as reads and the document as a create (grid.py).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from strands import tool

from agent.ingest.store import PENDING, Store, kind_of
from agent.runtime.model_call import ModelCall, ModelCallError
from agent.tools.documents.create import create
from agent.tools.documents.tool import _failed, _free

#: Supported inputs: what the ingest store reads, and plain text.
TEXT_SUFFIXES = {".txt", ".md"}
MAX_FILES = 60
MAX_COLUMNS = 12
#: Per file or section, what one question shows the model (Gemma's prompt is read at ~2,300 tok/s).
MAX_TEXT = 8000
MAX_SECTIONS = 24
MAX_CHANGES = 40
WAIT = 60.0

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class PipelineError(Exception):
    """Why the files could not be worked on; the message is for the model."""


def norm(text: str) -> str:
    """Text compared loosely: letters, digits and points only ("9,123.45" in "Amount due: 9 123.45")."""
    return re.sub(r"[^0-9a-z.]", "", text.lower().replace(",", ""))


def grounded(value: str, text: str) -> bool:
    return bool(norm(value)) and norm(value) in norm(text)


def numbers_grounded(sentence: str, text: str) -> list[str]:
    """The numbers in `sentence` that `text` does not have."""
    have = norm(text)
    return [n for n in _NUMBER.findall(sentence) if norm(n).rstrip(".") not in have]


# ----------------------------------------------------------------- reading --


def read_blocks(store: Store, chat: str, target: Path) -> list[dict[str, Any]]:
    """The file's blocks in order, every page read (OCR included), or PipelineError."""
    if not target.is_file():
        raise PipelineError(f"no file {target.name}")
    if target.suffix.lower() in TEXT_SUFFIXES:
        text = target.read_text(encoding="utf-8", errors="replace")
        return [{"kind": "para", "text": p.strip()} for p in re.split(r"\n\s*\n", text) if p.strip()]
    if kind_of(target) not in ("pdf", "docx"):
        raise PipelineError(f"{target.name} is not a PDF, Word or text file")
    sha = store.submit(target, chat)
    e = store.wait(sha, lambda e: e["status"] != "queued", WAIT) if sha else None
    if sha is None or e is None:
        raise PipelineError(f"{target.name} is still being read; try again in a moment")
    if e["status"] == "failed":
        raise PipelineError(f"{target.name} could not be read: {e['error']}")
    if e.get("pages"):
        store.want(sha, list(range(1, e["pages"] + 1)))
        e = store.wait(sha, lambda e: not any(s in PENDING for s in e["page_status"]), WAIT) or e
        if any(s in PENDING for s in e["page_status"]):
            raise PipelineError(f"{target.name} is still being read (OCR); try again in a moment")
    return store.blocks(sha)


def _whole(blocks: list[dict[str, Any]]) -> str:
    return "\n\n".join(b["text"] for b in blocks if b.get("text"))


# ------------------------------------------------------------ extract_table --


ROW_SYSTEM = ("You copy fields out of one document. For each field give the value exactly as it is written in "
              'the document. If the document does not say, give "". Never invent or compute a value.')


def _amount(value: str) -> Decimal | None:
    core = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
    try:
        return Decimal(core) if core else None
    except InvalidOperation:
        return None


def _cell(value: str) -> str:
    return " ".join(value.replace("|", "/").split())


def extract(ask: ModelCall, files: list[tuple[str, list[dict[str, Any]]]], columns: list[str],
            total: str = "") -> dict[str, Any]:
    """`{"rows": [[file, values...]], "flagged": [...], "total": Decimal | None}`."""
    schema = {"type": "object", "additionalProperties": False, "required": columns,
              "properties": {c: {"type": "string", "maxLength": 200} for c in columns}}
    rows, flagged = [], []
    for name, blocks in files:
        text = _whole(blocks)
        if len(text) > MAX_TEXT:
            flagged.append(f"{name}: only its first {MAX_TEXT:,} characters were read")
        text = text[:MAX_TEXT]
        answer = ask.ask(f"Document {name}:\n{text}\n\nFields: {', '.join(columns)}", schema,
                         system=ROW_SYSTEM, name="row", max_tokens=400, temperature=0.1)
        values = []
        for c in columns:
            v = _cell(str((answer or {}).get(c) or "")) if isinstance(answer, dict) else ""
            if v and not grounded(v, text):
                flagged.append(f"{name}: {c} \"{v}\" is not in the file, left empty")
                v = ""
            elif not v:
                flagged.append(f"{name}: no {c} found")
            values.append(v)
        rows.append([name, *values])
    sum_ = None
    if total:
        i = columns.index(total) + 1
        sum_ = Decimal(0)
        for row in rows:
            if row[i] and (n := _amount(row[i])) is not None:
                sum_ += n
            elif row[i]:
                flagged.append(f"{row[0]}: {total} \"{row[i]}\" is not a number, not in the total")
    return {"rows": rows, "flagged": flagged, "total": sum_}


def table_markdown(title: str, columns: list[str], rows: list[list[str]], total: str = "",
                   sum_: Decimal | None = None) -> str:
    head = ["File", *columns]
    lines = [f"# {title}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    if total and sum_ is not None:
        i = columns.index(total) + 1
        lines.append("| " + " | ".join("Total" if k == 0 else f"{sum_:.2f}" if k == i else "" for k in range(len(head))) + " |")
    return "\n".join(lines)


# ------------------------------------------------------------ write_summary --


SECTION_SYSTEM = ("You summarise one section of a document. Give one sentence that states the section's main "
                  "point, and its single most important figure exactly as written (the number with its unit), "
                  'or "" if it has none. Use only this section\'s text.')


def _heading_line(line: str, before: str | None) -> bool:
    """A short title line on its own: not a sentence, after a finished sentence or at the start."""
    words = line.split()
    return (2 <= len(line) <= 70 and 1 <= len(words) <= 9 and (line[0].isupper() or line[0].isdigit())
            and not line.endswith((".", ",", ";", ":")) and (before is None or before.endswith((".", "!", "?", ":"))))


def sections(blocks: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """`(title, text)` for each section: Word headings, else title lines in a PDF, else runs of pages."""
    found: list[tuple[str, list[str]]] = []
    if any(b.get("kind") == "heading" for b in blocks):
        for b in blocks:
            if b.get("kind") == "heading" and int(b.get("level") or 1) <= 2:
                found.append((b["text"], []))
            elif found:
                found[-1][1].append(b["text"])
            elif b.get("text"):
                found.append(("Introduction", [b["text"]]))
    else:
        for b in blocks:
            lines = [ln.strip() for ln in str(b.get("text") or "").splitlines() if ln.strip()]
            before = None
            for ln in lines:
                # A title line right after another (a document title, then its first section) counts too.
                if _heading_line(ln, None if found and not found[-1][1] else before):
                    found.append((ln, []))
                elif found:
                    found[-1][1].append(ln)
                else:
                    found.append(("Introduction", [ln]))
                before = ln
    out = [(t, "\n".join(body)) for t, body in found if len("\n".join(body)) >= 80]
    if len(out) < 2:   # no structure to follow: cut by pages
        pages: dict[int, list[str]] = {}
        for b in blocks:
            pages.setdefault(int(b.get("page") or 1), []).append(b["text"])
        keys = sorted(pages)
        step = max(1, -(-len(keys) // 12))
        out = [(f"Pages {keys[i]}-{keys[min(i + step, len(keys)) - 1]}" if step > 1 else f"Page {keys[i]}",
                "\n".join(t for k in keys[i:i + step] for t in pages[k])) for i in range(0, len(keys), step)]
    while len(out) > MAX_SECTIONS:   # merge the shortest neighbours
        i = min(range(len(out) - 1), key=lambda k: len(out[k][1]) + len(out[k + 1][1]))
        out[i:i + 2] = [(f"{out[i][0]}; {out[i + 1][0]}", out[i][1] + "\n" + out[i + 1][1])]
    return out


def summarise(ask: ModelCall, parts: list[tuple[str, str]]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """`[(title, sentence, figure)]` and what was flagged. A sentence whose numbers are
    not in its section is asked again once, then left out."""
    schema = {"type": "object", "additionalProperties": False, "required": ["sentence", "figure"],
              "properties": {"sentence": {"type": "string", "maxLength": 300},
                             "figure": {"type": "string", "maxLength": 60}}}
    points, flagged = [], []
    for title, text in parts:
        text = text[:MAX_TEXT]
        prompt, wrong = f"Section: {title}\n\n{text}", []
        for _ in range(2):
            answer = ask.ask(prompt, schema, system=SECTION_SYSTEM, name="point", max_tokens=200, temperature=0.1)
            sentence = " ".join(str((answer or {}).get("sentence") or "").split()) if isinstance(answer, dict) else ""
            figure = " ".join(str((answer or {}).get("figure") or "").split()) if isinstance(answer, dict) else ""
            wrong = numbers_grounded(sentence, text) + ([figure] if figure and not grounded(figure, text) else [])
            if sentence and not wrong:
                points.append((title, sentence, figure))
                break
            prompt += "\n\nUse only numbers written in this section, exactly as written."
        else:
            flagged.append(f"{title}: no sentence could be checked against the section"
                           + (f" ({', '.join(wrong)} is not in it)" if wrong else ""))
    return points, flagged


# -------------------------------------------------------- compare_documents --


CHANGE_SYSTEM = ("You describe one change between two versions of a document in one short sentence: what was "
                 "changed, added or removed. Use only the text shown.")


def _units(blocks: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """`(where, text)`: each paragraph, and each table row on its own."""
    out, where = [], ""
    for b in blocks:
        if b.get("kind") == "heading":
            where = b["text"]
        label = where or (f"page {b['page']}" if b.get("page") else "")
        lines = str(b.get("text") or "").splitlines() if b.get("kind") in ("table", "rows") else [str(b.get("text") or "")]
        out += [(label, " ".join(ln.split())) for ln in lines if ln.strip()]
    return out


def changes(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, str]]:
    """What changed, by code: `{"where", "before", "after"}` in document order."""
    a, b = _units(old), _units(new)
    matcher = difflib.SequenceMatcher(a=[t for _, t in a], b=[t for _, t in b], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        where = (b[j1][0] if j1 < len(b) else a[i1][0] if i1 < len(a) else "") or ""
        out.append({"where": where, "before": "\n".join(t for _, t in a[i1:i2]),
                    "after": "\n".join(t for _, t in b[j1:j2])})
    return out


def describe(ask: ModelCall, found: list[dict[str, str]]) -> list[str]:
    schema = {"type": "object", "additionalProperties": False, "required": ["change"],
              "properties": {"change": {"type": "string", "maxLength": 250}}}
    out = []
    for c in found:
        before, after = c["before"][:3000], c["after"][:3000]
        answer = ask.ask(f"Before:\n{before or '(nothing)'}\n\nAfter:\n{after or '(nothing)'}", schema,
                         system=CHANGE_SYSTEM, name="change", max_tokens=120, temperature=0.1)
        text = " ".join(str((answer or {}).get("change") or "").split()) if isinstance(answer, dict) else ""
        if not text or numbers_grounded(text, before + "\n" + after):
            text = ("Removed: " + before[:200] if not after else "Added: " + after[:200] if not before
                    else f'Changed from "{before[:150]}" to "{after[:150]}"')
        out.append(text)
    return out


# -------------------------------------------------------------------- tools --


def pipeline_tools(store: Store, chat: str, workspace: Path, resolve: Callable[[str], Path],
                   shown: Callable[[Path], str], ask: ModelCall) -> dict[str, Any]:

    def _inputs(names: list[str]) -> list[Path]:
        out: list[Path] = []
        for n in names:
            p = resolve(str(n))
            if p.is_dir():
                out += sorted(f for f in p.iterdir() if f.is_file() and not f.name.startswith(".")
                              and (kind_of(f) in ("pdf", "docx") or f.suffix.lower() in TEXT_SUFFIXES))
            else:
                out.append(p)
        return list(dict.fromkeys(out))

    def _write(path: str, markdown: str) -> tuple[Path, str]:
        asked = resolve(path)
        target = _free(asked)
        create(target, markdown, base=workspace)
        renamed = f" ({asked.name} already exists, so this is {target.name})" if target != asked else ""
        return target, renamed

    @tool(name="extract_table")
    def extract_table(files: list[str], columns: list[str], path: str, total: str = "") -> Any:
        """Make a spreadsheet with one row per file: each column's value copied out of that file.

        Use it for invoices, receipts, CVs, forms: anything where the same facts are in many files.
        Each value is checked against its file, and the total is added up by code.

        Args:
            files: The files (PDF, Word or text) by name, or a folder to take every such file from.
            columns: The facts to copy, e.g. ["invoice number", "vendor", "date", "amount due"].
            path: The .xlsx to create, e.g. "invoices.xlsx".
            total: Optional: the column to add up, e.g. "amount due".
        """
        columns = [" ".join(str(c).split()) for c in columns if str(c).strip()][:MAX_COLUMNS]
        if not columns:
            return _failed("give the columns to copy, e.g. columns=[\"vendor\", \"amount due\"]")
        if total and total not in columns:
            return _failed(f"total must be one of the columns: {', '.join(columns)}")
        if not path.lower().endswith((".xlsx", ".csv", ".docx", ".md")):
            return _failed("path must end in .xlsx (or .csv, .docx, .md)")
        targets = _inputs(files)
        if not targets:
            return _failed("no files given")
        if len(targets) > MAX_FILES:
            return _failed(f"{len(targets)} files; at most {MAX_FILES} at once")
        try:
            read = [(p.name, read_blocks(store, chat, p)) for p in targets]
            made = extract(ask, read, columns, total)
            target, renamed = _write(path, table_markdown(Path(path).stem, columns, made["rows"], total, made["total"]))
        except (PipelineError, ModelCallError) as exc:
            return _failed(str(exc))
        preview = "\n".join(" | ".join(r) for r in made["rows"][:40])
        lines = [f"Created {shown(target)}{renamed}: {len(made['rows'])} rows, one per file, columns File, "
                 f"{', '.join(columns)}.", "", "File | " + " | ".join(columns), preview]
        if made["total"] is not None:
            lines += ["", f"Total of {total}, added by code: {made['total']:,.2f}. Give the user exactly this figure."]
        if made["flagged"]:
            lines += ["", "Not filled in (tell the user):", *(f"- {f}" for f in made["flagged"][:30])]
        return "\n".join(lines)

    @tool(name="write_summary")
    def write_summary(file: str, path: str) -> Any:
        """Write a summary of a long document: one bullet per section, each with its key figure.

        It reads every page, section by section, and checks every number against its section.

        Args:
            file: The document to summarise (PDF, Word or text).
            path: The summary to create: .docx, .pdf or .md, e.g. "summary.docx".
        """
        if not path.lower().endswith((".docx", ".pdf", ".md", ".txt")):
            return _failed("path must end in .docx, .pdf or .md")
        source = resolve(file)
        try:
            parts = sections(read_blocks(store, chat, source))
            points, flagged = summarise(ask, parts)
            if not points:
                return _failed("no section could be summarised with checked figures: " + "; ".join(flagged[:5]))
            body = "\n".join(f"- **{t}:** {s}" for t, s, _ in points)
            target, renamed = _write(path, f"# Summary of {source.stem}\n\n{body}")
        except (PipelineError, ModelCallError) as exc:
            return _failed(str(exc))
        out = f"Created {shown(target)}{renamed} from {len(parts)} sections of {source.name}:\n\n{body}"
        if flagged:
            out += "\n\nLeft out (tell the user):\n" + "\n".join(f"- {f}" for f in flagged)
        return out

    @tool(name="compare_documents")
    def compare_documents(old: str, new: str, path: str = "") -> Any:
        """Find every change between two versions of a document, and describe each one.

        Code finds the changes; nothing is missed or invented. Optionally writes them to a document.

        Args:
            old: The earlier version (PDF, Word or text).
            new: The later version.
            path: Optional: a .docx, .pdf or .md to write the changes to, e.g. "changes.docx".
        """
        if path and not path.lower().endswith((".docx", ".pdf", ".md", ".txt")):
            return _failed("path must end in .docx, .pdf or .md")
        a, b = resolve(old), resolve(new)
        try:
            found = changes(read_blocks(store, chat, a), read_blocks(store, chat, b))
            if not found:
                return f"{a.name} and {b.name} have the same text: no changes."
            more = len(found) - MAX_CHANGES
            found = found[:MAX_CHANGES]
            words = describe(ask, found)
            lines = [f"{i}. {f'[{c['where']}] ' if c['where'] else ''}{w}" for i, (c, w) in enumerate(zip(found, words, strict=True), 1)]
            made = ""
            if path:
                rows = "\n".join(f"| {i} | {_cell(c['where'])} | {_cell(c['before'][:300])} | {_cell(c['after'][:300])} | {_cell(w)} |"
                                 for i, (c, w) in enumerate(zip(found, words, strict=True), 1))
                target, renamed = _write(path, f"# Changes from {a.name} to {b.name}\n\n"
                                               "| # | Where | Before | After | Change |\n|---|---|---|---|---|\n" + rows)
                made = f"Created {shown(target)}{renamed}. "
        except (PipelineError, ModelCallError) as exc:
            return _failed(str(exc))
        return (f"{made}{len(found)} changes from {a.name} to {b.name}"
                + (f" (and {more} more not shown)" if more > 0 else "") + ":\n" + "\n".join(lines))

    return {"extract_table": extract_table, "write_summary": write_summary, "compare_documents": compare_documents}


__all__ = ["changes", "extract", "grounded", "numbers_grounded", "pipeline_tools", "read_blocks", "sections",
           "summarise", "table_markdown"]
