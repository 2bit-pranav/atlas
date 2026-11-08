"""What the model is sent for a message beyond the user's text: attachments,
@ mentions, PDF links, images and recordings; removing a retry's hint after."""


from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.config.settings import (
    Settings,
)
from agent.integrations.skills.catalog import SkillManager
from agent.platform.winpaths import model_path
from agent.tools.manager import ToolManager
from agent.tools.reading import DOCUMENTS
from server.services.workspace import _scan

_IMAGE = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "webp": "webp"}


_AUDIO = {"wav": "wav", "mp3": "mp3"}


def _media_kind(f: dict[str, Any]) -> str | None:
    ext = Path(str(f.get("name", ""))).suffix.lower().lstrip(".")
    return "image" if ext in _IMAGE else "audio" if ext in _AUDIO else None


def _media_blocks(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Image and audio attachments as Strands content blocks."""
    blocks = []
    for f in files:
        ext = Path(str(f["name"])).suffix.lower().lstrip(".")
        data = Path(str(f["path"])).read_bytes()
        if ext in _IMAGE:
            blocks.append({"image": {"format": _IMAGE[ext], "source": {"bytes": data}}})
        elif ext in _AUDIO:
            blocks.append({"audio": {"format": _AUDIO[ext], "source": {"bytes": data}}})
    return blocks


#: `@name`, or `@"a name with spaces"` -- what the composer inserts.
_MENTION = re.compile(r'(?<![\w@])@(?:"([^"\n]+)"|([\w.-]+))')


#: A PDF given as a link in the message: on the web, or a local file:// path.
_PDF_LINK = re.compile(r"""(?:https?|file)://[^\s<>"')\]]+?\.pdf(?:\?[^\s<>"')\]]*)?(?=[\s<>"')\],.;!?]|$)""", re.I)


def _reader(name: str) -> str | None:
    """The read tool for a document, by its extension: `read_pdf(path="x.pdf")`."""
    tool = DOCUMENTS.get(Path(name.split("?", 1)[0]).suffix.lower())
    return f'{tool}(path="{name}")' if tool else None


def _link_guidance(user_text: str, settings: Settings) -> str:
    """The exact call for each PDF link, as attachments get one.

    Without it the model tried the `read` tool on the URL, which cannot fetch,
    and asked the user to upload the file instead.
    """
    lines = []
    for link in dict.fromkeys(_PDF_LINK.findall(user_text)):
        if link.lower().startswith(("http://", "https://")) and (call := _reader(link)):
            lines.append(f"- {link}: read it with {call}")
    return ("PDF links in this message (read_pdf downloads them into your workspace):\n"
            + "\n".join(lines)) if lines else ""


def _mention_guidance(user_text: str, settings: Settings, mcp: Any,
                      workspace: Path | None = None) -> str:
    """`@name` in a message, resolved against workspace files, MCP servers,
    tools and skills.

    The composer's @ menu inserts these. A small model needs the instruction
    spelled out: asked to "use @fetch" it would otherwise still pick whichever
    tool looked closest. Resolved at run time, so a retry or an edit of the
    message gets the same instruction. Unknown names are left alone -- an
    email address or a handle is not a mention.
    """
    names = list(dict.fromkeys(q or n for q, n in _MENTION.findall(user_text or "")))
    if not names:
        return ""
    skills = {s["folder"]: s["name"] for s in SkillManager(settings).enabled()}
    skills.update({s: s for s in list(skills.values())})
    servers = {s["name"]: [t["agent_name"] for t in s["tools"] if t["enabled"]]
               for s in mcp.describe() if s["status"] == "connected"}
    manager = ToolManager(settings)
    tools = set(manager.builtin_tools()) | set(manager.atlas_tools())
    for server_tools in servers.values():
        tools |= set(server_tools)

    files = _scan(workspace) if workspace is not None else {}
    lines = []
    for name in names:
        if name in files:
            call = _reader(name)
            lines.append(f"- `{name}` is the file `{name}` in your workspace"
                         + (f"; read it with {call}" if call else "."))
        elif name in servers:
            lines.append(f"- Use the tools of the MCP server `{name}` "
                         f"({', '.join(servers[name]) or 'none enabled'}), not built-in tools that "
                         "do something similar.")
        elif name in tools:
            lines.append(f"- Use the `{name}` tool for this.")
        elif name in skills:
            lines.append(f"- Use the `{skills[name]}` skill: load it with the `skills` tool first.")
    if not lines:
        return ""
    return "The user picked these with @ in their message:\n" + "\n".join(lines)


def _agent_text(user_text: str, files: list[dict[str, Any]],
                refs: list[dict[str, Any]] | None = None, workspace: Path | None = None) -> str:
    """What the agent is told, as opposed to what the user typed.

    A file the model has never heard of is a file it will not look for. So
    attachments are named explicitly, each with the exact call that reads it. Built here rather than stored, so the stored `user_text`
    stays exactly what was typed -- which is what the transcript shows and what
    a retry replays.
    """
    parts = [user_text]
    quoted = [r for r in refs or [] if isinstance(r, dict) and r.get("quote")]
    if quoted:
        # Quoted from a file (the former preview panel). Named with the file's path, so a
        # request like "reword this" can go straight to the edit tools.
        parts.append("The user selected these passages and is asking about them:\n" + "\n".join(
            f"- from {r.get('file')} at {model_path(r['path']) if r.get('path') else r.get('file')}: "
            f'"{r["quote"]}"' for r in quoted))
    lines = []
    for f in files:
        if not isinstance(f, dict) or not f.get("path"):
            continue
        # The exact call for each file. A file in the workspace is named bare (the tools
        # place it there), never by the workspace's path: the model copied its chat id
        # wrong and landed in another chat's folder (2026-11-05).
        here = workspace is not None and Path(str(f["path"])).parent == workspace
        name = f["name"] if here else model_path(f["path"])
        line = f"- {name} ({f.get('size', 0)} bytes{', in your workspace' if here else ''})"
        if call := _reader(name):
            line += f". Read it with {call}"
            # Without this the model read the file and rewrote it with
            # create_document even when asked to merge or convert it.
            skill = Path(name).suffix.lower().lstrip(".").replace("xlsm", "xlsx")
            line += f" (to merge, split, combine or convert it instead, load the {skill} skill first)"
        elif _media_kind(f) == "image":
            # Sent with the message, so seen at once; named so it can be looked at again
            # later. Unnamed, the model guessed "image.png" on a follow-up (2026-11-07).
            line += f": shown to you with this message. To look at it again later, read_image(path=\"{name}\")"
        elif _media_kind(f) == "audio":
            line += ": sent to you with this message, to listen to"
        elif _media_kind(f) is None:
            line += f". Read it with read_text(path=\"{name}\")"
            # A long file read from the top is answered from its first lines ("no errors in
            # this log"); told the size and the search form up front, the model searches.
            if (count := _line_count(Path(str(f["path"])))) > 150:
                line += f"; it has {count:,} lines, so to find something use read_text(path=\"{name}\", search=\"words\")"
        lines.append(line)
    if lines:
        parts.append("Files attached to this message (use the paths exactly as written):\n"
                     + "\n".join(lines))
    return "\n\n".join(p for p in parts if p).strip()


def _line_count(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
    except OSError:
        return 0


def _strip_hint(messages: list[dict[str, Any]], start: int, hint: str) -> None:
    """Remove a retry hint from the user message before the snapshot is saved.

    The hint is for this one attempt. Left in history it would be re-read on
    every later turn and tell the model to "answer differently" forever.
    """
    if start >= len(messages):
        return
    for block in messages[start].get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            block["text"] = block["text"].replace(f"\n\n{hint}", "")


__all__ = []
