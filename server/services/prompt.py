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
from agent.integrations.skills.readers import reader_command
from agent.platform.winpaths import model_path
from agent.tools.manager import ToolManager
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


def _link_guidance(user_text: str, settings: Settings) -> str:
    """The exact command for each PDF link, as attachments get one.

    Without it the model tried the `read` tool on the URL, which cannot fetch,
    and asked the user to upload the file instead.
    """
    lines = []
    for link in dict.fromkeys(_PDF_LINK.findall(user_text)):
        from urllib.parse import urlparse

        if command := reader_command(settings, urlparse(link).path, link):  # the path names the type, not ?query
            lines.append(f"- {link}: read it with: {command}")
    return ("PDF links in this message (the reader downloads them into your workspace):\n"
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
            shown = model_path(str(workspace / name))  # type: ignore[operator]
            command = reader_command(settings, name, name)
            lines.append(f"- `{name}` is the file at {shown}"
                         + (f"; read it with: {command}" if command else "."))
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
                refs: list[dict[str, Any]] | None = None,
                reader: Any = None, workspace: Path | None = None) -> str:
    """What the agent is told, as opposed to what the user typed.

    Nothing is parsed at upload, but a file the model has never heard of is a
    file it will not look for. So attachments are named explicitly, as
    absolute paths. Built here rather than stored, so the stored `user_text`
    stays exactly what was typed -- which is what the transcript shows and what
    a retry replays.
    """
    parts = [user_text]
    quoted = [r for r in refs or [] if isinstance(r, dict) and r.get("quote")]
    if quoted:
        # Quoted from a file (the former preview panel). Named with the file's path, so a
        # request like "reword this" can go straight to edit_document.
        parts.append("The user selected these passages and is asking about them:\n" + "\n".join(
            f"- from {r.get('file')} at {model_path(r['path']) if r.get('path') else r.get('file')}: "
            f'"{r["quote"]}"' for r in quoted))
    lines = []
    for f in files:
        if not isinstance(f, dict) or not f.get("path"):
            continue
        shown = model_path(f["path"])
        line = f"- {f.get('name')} at {shown} ({f.get('size', 0)} bytes)"
        # The exact command for a pdf/docx/xlsx: the model runs it directly
        # instead of trying `read` first and loading the skill to find out.
        # Commands start in the workspace, so a file there is named bare.
        here = workspace is not None and Path(str(f["path"])).parent == workspace
        if reader is not None and (command := reader(str(f["path"]), f["name"] if here else shown)):
            line += f". Read it with: {command}"
            # Without this the model read the file and rewrote it with
            # create_document even when asked to merge or convert it.
            skill = command.split("$ATLAS_SKILLS/", 1)[-1].split("/", 1)[0]
            line +=f" (to merge, split, combine or convert it instead, load the {skill} skill first)"
        elif reader is not None and _media_kind(f) is None:  # images and audio are sent to the model as they are
            name = f["name"] if here else shown
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
