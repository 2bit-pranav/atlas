"""Writing documents: create one from Markdown, or change one block or cell.

These tools are not in the agent's list until a skill that writes is loaded
(`SKILL_TOOLS`, registered by `runtime/skill_tools.py`): reading is global,
writing comes with its skill, so the tool list a chat starts with stays small.

The model writes **Markdown**, which a small model writes reliably, and these
converters turn it into docx, pdf or xlsx. Hand-written JSON piped through
`echo '...' |` broke on the first apostrophe and on any slip in nesting, and
the model then wrote plain text into a `.docx` -- a corrupt file.

Guarantees:

1. **Never a corrupt file.** Each document is written to a temporary file,
   reopened with its own library to prove it parses, and only then moved into
   place. A failure leaves the previous version untouched.
2. **Never a lost file.** `create_document` does not replace an existing file:
   it saves under a new name. After failed edits the model regenerated a whole
   workbook over the original, with one month's figures replaced by another's
   (decisions.md, 2026-11-03).
3. **Edits by address.** `edit_docx` and `set_cell` take the block or cell the
   reader printed, and only for a version of the file this chat attached or read.
4. **One precise error,** in words the model can act on, not a traceback.
5. **Binary files are only written through these tools.** The tool policy
   (`policy.py`) refuses the plain `write`/`edit` tools and shell text writes
   on .docx/.xlsx/.pdf/.pptx.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from strands import tool

from agent.ingest.store import Store
from agent.tools.documents.base import DocumentError, _atomic
from agent.tools.documents.blocks import edit_docx_block, set_xlsx_cell
from agent.tools.documents.create import create
from agent.tools.documents.docx import _check_docx
from agent.tools.documents.xlsx import _check_xlsx

#: Which writing tools each bundled skill brings with it.
SKILL_TOOLS: dict[str, tuple[str, ...]] = {
    "pdf": ("create_document",),
    "docx": ("create_document", "edit_docx"),
    "xlsx": ("create_document", "set_cell"),
}


def skill_of(tool_name: str) -> str | None:
    """The first skill that brings `tool_name`, for "load the docx skill first"."""
    return next((s for s, names in SKILL_TOOLS.items() if tool_name in names), None)


def _failed(message: str) -> dict[str, Any]:
    """An error result, so the failure counts as one (agent/recovery/ nudges on it)."""
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


def _free(target: Path) -> Path:
    """`target`, or the first `name-2.ext`, `name-3.ext` ... that does not exist."""
    n, out = 2, target
    while out.exists():
        out, n = target.with_name(f"{target.stem}-{n}{target.suffix}"), n + 1
    return out


def document_tools(workspace: Path, shown: Callable[[Path], str], resolve: Callable[[str], Path],
                   store: Store, chat: str) -> dict[str, Any]:
    """The writing tools for one chat, by name. `resolve` places a path as every
    file tool does (`placement.locate`)."""

    def _current(target: Path) -> str | None:
        """Why the file cannot be edited by address, or None. It must be a version
        this chat attached or read: block and cell ids belong to that version."""
        if not target.is_file():
            names = sorted(p.name for p in workspace.glob("*") if p.is_file() and not p.name.startswith("."))
            return f"no file {target.name}. Files in your workspace: {', '.join(names) or 'none'}."
        sha = store.identify(target)
        if store.owner_of(chat, sha[:12]) != sha:
            return f"{target.name} has not been read in this chat, or it changed since. Read it first."
        return None

    @tool(name="create_document")
    def create_document(path: str, content: str, title: str = "") -> Any:
        """Create a Word (.docx), PDF (.pdf) or Excel (.xlsx) file from Markdown. Also .md/.txt/.csv.

        Write the whole document as Markdown in `content`: # headings, paragraphs,
        **bold**, *italic*, - bullets, 1. numbered lists, tables
        (| Name | Total |, then |---|---|, then one row per line), and images
        as ![caption](path) on their own line -- to keep a source document's
        images, copy the ![...](asset:...) lines its reader printed, exactly. For .xlsx,
        every Markdown table becomes a sheet named after the heading above it.
        An existing file is never replaced: the new one gets a new name. To change
        an existing document use edit_docx or set_cell.

        Args:
            path: File name (saved in your workspace) or a full path, ending in .docx, .pdf or .xlsx.
            content: The document, as Markdown.
            title: Optional document title.
        """
        asked = resolve(path)
        target = _free(asked)
        try:
            info = create(target, content, title or None, base=workspace,
                          asset=lambda ref: store.asset(chat, ref))
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001 - the model needs words, not a traceback
            return _failed(f"could not create {target.name}: {type(exc).__name__}: {exc}")
        missing = info.pop("missing_images", [])
        detail = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in info.items() if v)
        size = target.stat().st_size
        renamed = (f" {asked.name} already exists and was left unchanged, so this is saved as "
                   f"{target.name}." if target != asked else "")
        note = (f" These images were not found and were left out: {', '.join(missing)}. "
                "Use the exact image lines the reader printed." if missing else "")
        return (f"Created {shown(target)} ({size:,} bytes{'; ' + detail if detail else ''}).{renamed}{note} "
                "The user sees it as a download in the chat; tell them it is ready.")

    @tool(name="edit_docx")
    def edit_docx(path: str, block: str, text: str) -> Any:
        """Change one paragraph or one table cell of a Word document, keeping everything else.

        `block` is an id read_docx printed: a paragraph like b12, or a table cell like t1.r3.c2
        (table 1, row 3, column 2). `text` is the block's whole new text,
        e.g. block="t1.r3.c3", text="18 days".

        Args:
            path: The .docx file name in your workspace, or its full path.
            block: The paragraph or cell id from read_docx.
            text: The new text for that paragraph or cell.
        """
        target = resolve(path)
        if target.suffix.lower() != ".docx":
            hint = " Use set_cell for a workbook." if target.suffix.lower() in (".xlsx", ".xlsm") else ""
            return _failed(f"{target.name} is not a .docx.{hint}")
        if (why := _current(target)) is not None:
            return _failed(why)
        try:
            old = _atomic(target, lambda p: {"old": edit_docx_block(target, p, block, text)}, _check_docx)["old"]
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _failed(f"could not edit {target.name}: {type(exc).__name__}: {exc}")
        store.submit(target, chat)
        return f'Edited {shown(target)}, {block.strip()}: "{old[:200]}" is now "{text[:200]}".'

    @tool(name="set_cell")
    def set_cell(path: str, cell: str, value: str) -> Any:
        """Set one cell of an Excel workbook, keeping everything else.

        `cell` is like B2, or Mar!B2 for a sheet other than the first; read_xlsx shows the
        row numbers and column letters. Numbers are stored as numbers,
        e.g. cell="Mar!B2", value="5000".

        Args:
            path: The .xlsx file name in your workspace, or its full path.
            cell: The cell, e.g. "Mar!B2".
            value: The new value.
        """
        target = resolve(path)
        if target.suffix.lower() not in (".xlsx", ".xlsm"):
            hint = " Use edit_docx for a Word document." if target.suffix.lower() == ".docx" else ""
            return _failed(f"{target.name} is not an Excel workbook.{hint}")
        if (why := _current(target)) is not None:
            return _failed(why)
        try:
            sheet, ref, old = _atomic(
                target, lambda p: {"r": set_xlsx_cell(target, p, cell, value)}, _check_xlsx)["r"]
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _failed(f"could not edit {target.name}: {type(exc).__name__}: {exc}")
        store.submit(target, chat)
        return f"Set {shown(target)}, {sheet}!{ref}: {old!r} is now {value!r}."

    return {"create_document": create_document, "edit_docx": edit_docx, "set_cell": set_cell}


__all__ = ["SKILL_TOOLS", "document_tools", "skill_of"]
