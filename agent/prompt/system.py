"""The system prompt: Atlas's instructions, runtime facts, and where each tool comes from."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.config import paths
from agent.config.settings import Settings
from agent.platform.winpaths import model_path


def _folders_line(settings: Settings) -> str:
    """The allowed folders, by path. Without it the model did not know it had any:
    asked about "my resume" it asked the user for the file (decisions.md, 2026-11-05).
    Names only, never contents, so the prompt (and llama.cpp's cache) stays stable."""
    from pathlib import Path

    folders = [model_path(Path(f).expanduser()) for f in settings.access.folders if f.strip()]
    if not folders:
        return ""
    return (f"- The user's own folders, which you may use: {', '.join(f'`{f}`' for f in folders)}. "
            "When the user mentions one of their files (\"my resume\", \"my notes\"), it is in these folders: "
            "find it with find_files, never by searching the web. Name a file in them by its path inside the "
            "folder (`Reports/invoices.xlsx`), or copy the full path a tool printed; never type a full path "
            "from memory.\n")


def _runtime_facts(settings: Settings, chat_id: str) -> str:
    """Facts about this machine that the model cannot know and cannot guess.

    Keep every line true: a confidently wrong instruction is worse than none,
    because the model tries to reconcile it with what it sees and loses a turn.

    * `python` resolves to the project's own interpreter, because the Windows
      environment puts the venv's `Scripts` directory first on PATH. So the
      commands written in every `SKILL.md` work exactly as printed.
    * Installs go through `python -m pip` so they land in Atlas's own venv,
      and the user approves each one (`policy.py`).
    * Today's date. Without it "last season" was read as two seasons ago. Only
      the date is here: it changes once a day, so llama.cpp's prompt cache
      survives. The time of day goes with each message (`clock_note`).

    Generated here rather than written into settings.json so it cannot drift
    from the interpreter that is actually running.
    """
    import sys

    workspace = paths.chat_dir(settings, chat_id)
    today = datetime.now().astimezone()
    return (
        f"Today is {today:%A, %d %B %Y}. Read \"last\", \"latest\", \"this year\" and "
        "similar words against this date, not against what you remember. Each "
        "message from the user ends with the time it was sent; use it, never repeat it.\n"
        "For facts from the web, prefer the original source (the organisation's "
        "own site, official docs, PyPI or GitHub releases) over sites that "
        "repeat it, and give the link you used.\n\n"
        "Running things on this machine:\n"
        f"- Python: `{sys.executable}`, and a bare `python` resolves to the "
        f"same interpreter. Either works.\n"
        f"- Your workspace for this chat is `{model_path(workspace)}`, and every shell "
        "command starts there, so a file in it is named by its name alone "
        "(\"exp4.pdf\"). Uploaded files are there, and files you create go "
        "there unless the user names another place.\n"
        + _folders_line(settings)
        + f"- Skill scripts are under `$ATLAS_SKILLS` ({model_path(paths.skills_dir(settings))}), "
        "as `$ATLAS_SKILLS/<skill>/scripts/<script>.py`.\n"
        "- Write paths with forward slashes, exactly as given. Backslashes break "
        "in this shell.\n"
        "- You may install what a task needs (`python -m pip install ...` for "
        "Python packages, so they go into Atlas's own environment; `npm install "
        "-g ...` for Node tools). The user is asked to approve every install "
        "first; if they decline, do not try another way."
    )


def _tool_sources(builtin: list[str], skills: list[str], extra: list[Any]) -> str:
    """Where each tool comes from, so "use the MCP one" has something to match.

    A small model sees a flat list of tool names. Asked to use an MCP server's
    fetch tool it kept calling a built-in tool with the same purpose, and asked for "MCP
    tools" it went looking for a skill.
    """
    from agent.integrations.mcp.pool import mcp_server_of

    servers: dict[str, list[str]] = {}
    for tool in extra:
        if (server := mcp_server_of(tool)) is not None:
            servers.setdefault(server, []).append(tool.tool_name)
    lines = ["Your tools, by where they come from:"]
    lines.append(f"- Built in: {', '.join(builtin) or 'none'}.")
    if "read_pdf" in builtin:
        # Reading needs no skill: loading one cost a call and 1-1.5k tokens per document task.
        lines.append("- Read files with read_pdf, read_docx, read_xlsx, read_text or read_image; no skill "
                     "is needed to read. To create or change a .docx, .xlsx or .pdf, load its skill "
                     "(docx, xlsx or pdf): that adds create_document, edit_docx and set_cell.")
    if "find_files" in builtin:
        lines.append("- Find files with find_files (by words) and list_folder (a folder's tree), not with shell "
                     "commands. Copy, move or rename with copy_file and move_file, delete with delete_file.")
    if skills:
        lines.append(f"- Skills (instructions, loaded with the `skills` tool; not tools themselves): "
                     f"{', '.join(skills)}.")
    for server, names in sorted(servers.items()):
        lines.append(f"- MCP server `{server}` (a separate program connected to Atlas): {', '.join(names)}.")
    if servers:
        lines.append("When the user names an MCP server, or says to use MCP tools, use that "
                     "server's tools, not a built-in tool that does something similar.")
    return "\n".join(lines)


def _compose_instructions(settings: Settings, chat_id: str, tool_sources: str = "") -> str:
    parts = [settings.system_prompt.strip()] if settings.system_prompt.strip() else []
    parts.append(_runtime_facts(settings, chat_id))
    if tool_sources:
        parts.append(tool_sources)
    return "\n\n".join(parts)


__all__ = []
