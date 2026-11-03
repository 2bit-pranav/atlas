"""Creating and editing documents: Markdown in, a valid file out.

The model writes **Markdown**, which a small model writes reliably, and these
converters turn it into docx, pdf or xlsx. Hand-written JSON piped through
`echo '...' |` broke on the first apostrophe and on any slip in nesting, and
the model then wrote plain text into a `.docx` -- a corrupt file.

Three guarantees:

1. **Never a corrupt file.** Each document is written to a temporary file,
   reopened with its own library to prove it parses, and only then moved into
   place. A failure leaves the previous version untouched.
2. **One precise error.** A failure says what was wrong in words the model can
   act on ("an xlsx needs a Markdown table"), not a traceback.
3. **Binary files are only written through these tools.** The tool policy
   (`policy.py`) refuses the plain `write`/`edit` tools on .docx/.xlsx/.pdf/.pptx.

Supported Markdown: headings, paragraphs, **bold**, *italic*, `code`, links,
bullet and numbered lists (nested), tables, fenced code, block quotes,
horizontal rules and images (`![caption](path)`). The pdf and docx readers
save a document's images and print them in that form, so rewriting a document
keeps its figures: the model copies the lines across.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from strands import tool

from agent.tools.documents.base import DocumentError
from agent.tools.documents.create import create
from agent.tools.documents.edit import edit

# --------------------------------------------------------------- tools --


def _failed(message: str) -> dict[str, Any]:
    """An error result, so the failure counts as one (agent/recovery/ nudges on it)."""
    return {"status": "error", "content": [{"text": f"Error: {message}"}]}


def document_tools(workspace: Path, shown: Callable[[Path], str],
                   folders: list[Path] | None = None,
                   asset: Callable[[str], Path | None] | None = None) -> list[Any]:
    """The two agent tools, bound to one chat's workspace.

    `shown` turns a path into the form the model is shown (`model_path`). A
    relative path is placed by `safety/placement.locate`, like every other tool's.
    """
    from agent.platform.winpaths import windows_path
    from agent.safety.placement import locate

    def resolve(path: str) -> Path:
        p = Path(windows_path(path)) if path.startswith("/") else Path(path)
        if p.is_absolute():
            return p
        return locate(path, workspace, folders or []) or workspace / p

    @tool(name="create_document")
    def create_document(path: str, content: str, title: str = "") -> Any:
        """Create a Word (.docx), PDF (.pdf) or Excel (.xlsx) file from Markdown. Also .md/.txt/.csv.

        Write the whole document as Markdown in `content`: # headings, paragraphs,
        **bold**, *italic*, - bullets, 1. numbered lists, tables
        (| Name | Total |, then |---|---|, then one row per line), and images
        as ![caption](path) on their own line -- to keep a source document's
        images, copy the ![...](asset:...) lines its reader printed, exactly. For .xlsx,
        every Markdown table becomes a sheet named after the heading above it.
        An existing file at `path` is replaced. Use this, never `write`, for
        .docx/.pdf/.xlsx files.

        Args:
            path: File name (saved in your workspace) or a full path, ending in .docx, .pdf or .xlsx.
            content: The document, as Markdown.
            title: Optional document title.
        """
        target = resolve(path)
        try:
            info = create(target, content, title or None, base=workspace, asset=asset)
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001 - the model needs words, not a traceback
            return _failed(f"could not create {target.name}: {type(exc).__name__}: {exc}")
        missing = info.pop("missing_images", [])
        detail = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in info.items() if v)
        size = target.stat().st_size
        note = (f" These images were not found and were left out: {', '.join(missing)}. "
                "Use the exact image paths the reader printed." if missing else "")
        return (f"Created {shown(target)} ({size:,} bytes{'; ' + detail if detail else ''}).{note} "
                "The user sees it as a download in the chat; tell them it is ready.")

    @tool(name="edit_document")
    def edit_document(path: str, find: str, replace: str, replace_all: bool = False) -> Any:
        """Change text inside an existing .docx, .xlsx, .md or .txt file, keeping everything else.

        `find` must match the document's text exactly, within one paragraph or one
        cell. Read the document first (with its skill) to copy the exact text.

        Args:
            path: The document's file name in your workspace, or its full path.
            find: The exact text to replace.
            replace: The new text. Empty to delete.
            replace_all: Replace every occurrence instead of exactly one.
        """
        target = resolve(path)
        try:
            n = edit(target, find, replace, replace_all)
        except DocumentError as exc:
            return _failed(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _failed(f"could not edit {target.name}: {type(exc).__name__}: {exc}")
        return f"Edited {shown(target)}: replaced {n} occurrence{'s' if n != 1 else ''}."

    return [create_document, edit_document]


__all__ = ["document_tools"]
