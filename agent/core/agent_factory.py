"""
build_agent: the one place that calls create_harness (agent/AGENTS.md).

Each manager resolves its part of the settings; this file asks them for their
parts and assembles one Strands Agent per turn, so a LIVE setting applies to
the next message. It needs no server.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from strands_harness import build_system_prompt, create_harness

from agent.core import paths
from agent.core.memory_manager import MemoryManager
from agent.core.shell_env import default_environment, model_path
from agent.core.model import AtlasLlamaCppModel
from agent.core.documents import document_tools
from agent.core.policy import Approver, Scope, ToolPolicy
from agent.core.resilience import LocalModelRetry, ToolFailureRecovery
from agent.core.session_manager import SessionManager
from agent.core.settings import Settings
from agent.core.skill_manager import SkillManager, reader_command
from agent.core.tool_manager import ToolManager

logger = logging.getLogger(__name__)


CONVERSATION_MANAGERS = {
    "null": "NullConversationManager",
    "sliding": "SlidingWindowConversationManager",
    "summarizing": "SummarizingConversationManager",
}


@dataclass
class RetryPlan:
    """What a retried turn does differently. `None` for every other turn."""

    #: Final answer text of the earlier versions, newest first.
    previous: list[str] = field(default_factory=list)


def build_model(
    settings: Settings,
    *,
    thinking: bool,
    retry: RetryPlan | None = None,
    observer: Callable[[dict[str, Any]], None] | None = None,
) -> AtlasLlamaCppModel:
    """The model for this turn.

    Sampling comes from settings every time, so a temperature change applies to
    the next turn rather than after a restart. A retry widens it (see
    `RetrySettings`): higher temperature, a presence penalty, a fresh seed.
    """
    s = settings.sampling
    params: dict[str, Any] = {
        "cache_prompt": True,
        "temperature": s.temperature,
        "top_p": s.top_p,
        "top_k": s.top_k,
        "min_p": s.min_p,
        "repeat_penalty": s.repeat_penalty,
        "max_tokens": s.max_tokens,
    }
    if s.presence_penalty:
        params["presence_penalty"] = s.presence_penalty
    if s.frequency_penalty:
        params["frequency_penalty"] = s.frequency_penalty

    if retry is not None:
        r = settings.retry
        params["temperature"] = min(2.0, s.temperature + r.temperature_boost)
        if r.presence_penalty:
            params["presence_penalty"] = r.presence_penalty
        if r.new_seed:
            params["seed"] = random.randrange(1, 2**31 - 1)

    return AtlasLlamaCppModel(
        base_url=f"http://127.0.0.1:{settings.ports.llama}",
        model_id=settings.model.name,
        enable_thinking=thinking,
        context_window_limit=settings.context.window or settings.model.context_size,
        params=params,
        # Timings on every chunk, so the context meter and tokens/s move while
        # the answer is still being written rather than jumping at the end.
        extra_body={"timings_per_token": True},
        observer=observer,
    )


def build_summarizer(settings: Settings) -> AtlasLlamaCppModel:
    """The model `web_fetch` uses to answer a question over a fetched page.

    The harness would otherwise reuse the main model object: with thinking on
    it reasoned before summarising a whole page, which is where most of a
    10-15 second fetch went, and its timings were counted as the turn's.
    Summarising needs no reasoning and only a short answer.
    """
    return AtlasLlamaCppModel(
        base_url=f"http://127.0.0.1:{settings.ports.llama}",
        model_id=settings.model.name,
        enable_thinking=False,
        context_window_limit=settings.context.window or settings.model.context_size,
        # 600 was too few: asked for a results table, the summariser hit the
        # cap and web_fetch failed with MaxTokensReachedException.
        params={"cache_prompt": True, "temperature": 0.2, "top_p": 0.9, "max_tokens": 2048},
    )


def retry_hint(settings: Settings, retry: RetryPlan) -> str:
    """The note appended to a retried question, quoting what came before.

    Appended to the *user message*, not the system prompt: the system prompt is
    the start of the cached prefix, so changing it would make llama-server
    re-read the whole conversation, and a small model also pays more attention
    to the last thing it was told. The run removes it from history before the
    snapshot is saved, so follow-ups never see it.
    """
    r = settings.retry
    lines = [r.instructions.strip()] if r.instructions.strip() else []
    if r.show_previous:
        for i, text in enumerate(retry.previous[: r.previous_limit], start=1):
            excerpt = " ".join(text.split())[: r.previous_chars]
            if excerpt:
                lines.append(f'Earlier answer {i}: "{excerpt}"')
    return "\n".join(lines)


def build_conversation_manager(settings: Settings) -> Any:
    """The SDK conversation manager named in settings, or Null.

    `NullConversationManager` is the default: the harness's `context_manager`
    is disabled (see `MemoryManager`), and until a trimming rule is measured,
    keeping the full history is better than trimming with an untested one.
    """
    from strands.agent import conversation_manager as cm

    name = settings.context.conversation_manager
    cls_name = CONVERSATION_MANAGERS.get(name, "NullConversationManager")
    cls = getattr(cm, cls_name, None)
    if cls is None:
        raise ValueError(
            f"context.conversation_manager={name!r} maps to {cls_name}, "
            "which this Strands build does not provide"
        )
    if cls_name == "NullConversationManager":
        return cls()
    kwargs: dict[str, Any] = {
        "proactive_compression": {
            "compression_threshold": settings.context.prune_trigger_ratio
        }
    }
    return cls(**kwargs)


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
        f"- Skill scripts are under `$ATLAS_SKILLS` ({model_path(paths.skills_dir(settings))}), "
        "as `$ATLAS_SKILLS/<skill>/scripts/<script>.py`.\n"
        "- Write paths with forward slashes, exactly as given. Backslashes break "
        "in this shell.\n"
        "- You may install what a task needs (`python -m pip install ...` for "
        "Python packages, so they go into Atlas's own environment; `npm install "
        "-g ...` for Node tools). The user is asked to approve every install "
        "first; if they decline, do not try another way."
    )


def clock_note(now: datetime | None = None) -> str:
    """The send time appended to every user message: local time and its offset."""
    now = (now or datetime.now()).astimezone()
    offset = now.strftime("%z")
    # Worded as context, not a line to copy: shorter, the model echoed it.
    return f"[Context, not to repeat: sent {now:%a %d %b %Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})]"


def build_agent(
    settings: Settings,
    *,
    chat_id: str,
    thinking: bool = False,
    restore_snapshot_id: str | None = None,
    session_manager: Any = None,
    tools: list | None = None,
    retry: RetryPlan | None = None,
    observer: Callable[[dict[str, Any]], None] | None = None,
    approver: Approver | None = None,
    sensitive: Callable[[str], bool] | None = None,
    tainted: Callable[[], bool] | None = None,
    sandbox: Any = None,
) -> Any:
    """Build one Strands `Agent` for one turn.

    Args:
        restore_snapshot_id: rewind to this snapshot before returning. The
            agent is built empty and then restored, never the other way round.
        tools: extra tools (MCP) added beside the built-ins.
        retry: set on a retried turn, to widen sampling.
        observer: receives model-call stats and retry notices for the run.
        approver: asks the user (installs, paths outside the allowed folders,
            sensitive MCP tools). Without one, those calls are refused with an
            explanation.
        sensitive: whether an MCP tool, by its agent-facing name, must ask first.
        tainted: whether web-page content has entered the turn (page tools).
    """
    tool_manager = ToolManager(settings)
    memory_manager = MemoryManager(settings)
    workspace_dir = paths.chat_dir(settings, chat_id)
    skill_manager = SkillManager(settings)

    if session_manager is None:
        session_manager = SessionManager(settings, chat_id).manager()

    model = build_model(settings, thinking=thinking, retry=retry, observer=observer)

    # settings.system_prompt is an *extension*: `instructions=` appends to the
    # harness prompt, so the harness guidance is always retained.
    builtin = tool_manager.builtin_tools()
    skills = skill_manager.enabled()
    atlas_tools = (document_tools(paths.chat_dir(settings, chat_id), model_path)
                   if settings.tools.documents else [])
    instructions = _compose_instructions(settings, chat_id, _tool_sources(
        [*builtin, *(t.tool_name for t in atlas_tools)], [s["name"] for s in skills], list(tools or [])))

    agent = create_harness(
        model=model,
        # The stock environment shells out to `sh`, which does not exist on
        # Windows. `sandbox=` is the documented seam; the shell tool picks it
        # up from `agent.sandbox` with no other change.
        sandbox=sandbox if sandbox is not None else default_environment(
            cwd=paths.chat_dir(settings, chat_id), skills=paths.skills_dir(settings)),
        instructions=instructions or None,
        session=session_manager,
        skills=[s["path"] for s in skills] or False,
        interventions=tool_manager.interventions(),
        tools=[*tool_manager.extra_tools(), *atlas_tools, *(tools or [])],
        # A mapping rather than a list, so web_fetch gets its own summarizer.
        builtin_tools={"*": False, **{name: True for name in builtin},
                       **({"web_fetch": {"model": build_summarizer(settings)}}
                          if "web_fetch" in builtin else {})},
        # The four off-switches, together. Any one of them alone is not enough.
        **memory_manager.harness_args(),
        conversation_manager=build_conversation_manager(settings),
        caching=False,
        # Strands' default handler prints every streamed token to stdout. Under
        # `atlas start` that console is cp1252, so an emoji or an arrow in an
        # answer raised UnicodeEncodeError and failed the whole run. Atlas
        # reads the stream itself and never wants the printout.
        callback_handler=None,
        # Recovery is hooks, not prompt text: see agent/core/resilience.py.
        retry_strategy=LocalModelRetry(settings.resilience, notify=observer),
        # Before a tool runs: one ordered policy (policy.py). After: recovery.
        hooks=[ToolPolicy(_scope(settings, workspace_dir), approver=approver,
                          ask_outside=settings.access.ask_outside, sensitive=sensitive, tainted=tainted,
                          reader=lambda p: reader_command(settings, p, _shown(p, workspace_dir))),
               ToolFailureRecovery(settings.resilience, notify=observer)],
    )

    if restore_snapshot_id:
        _restore(agent, session_manager, restore_snapshot_id, instructions)

    return agent


def _scope(settings: Settings, workspace: Path) -> Scope:
    """What a turn may touch without asking: its workspace and the allowed folders.

    Readable as well: the skills (their SKILL.md and scripts) and the Python
    environment that runs them.
    """
    import sys

    return Scope(
        workspace=workspace,
        folders=[Path(f).expanduser() for f in settings.access.folders if f.strip()],
        readable=[paths.skills_dir(settings), Path(sys.executable).resolve().parents[1]],
    )


def _shown(path: str, workspace: Path) -> str:
    """A file in the workspace by its bare name (commands start there), else as given."""
    from agent.core.shell_env import windows_path

    if path.lower().startswith(("http://", "https://", "file://")):
        return path  # a link: the pdf reader takes it as it is
    p = Path(windows_path(path))
    return p.name if p.parent.resolve() == workspace.resolve() else path


def _tool_sources(builtin: list[str], skills: list[str], extra: list[Any]) -> str:
    """Where each tool comes from, so "use the MCP one" has something to match.

    A small model sees a flat list of tool names. Asked to use an MCP server's
    fetch tool it kept calling the built-in `web_fetch`, and asked for "MCP
    tools" it went looking for a skill.
    """
    from agent.core.mcp_manager import mcp_server_of

    servers: dict[str, list[str]] = {}
    for tool in extra:
        if (server := mcp_server_of(tool)) is not None:
            servers.setdefault(server, []).append(tool.tool_name)
    lines = ["Your tools, by where they come from:"]
    lines.append(f"- Built in: {', '.join(builtin) or 'none'}.")
    if "read" in builtin:
        lines.append("- `read` is for text files and images only. A .pdf, .docx or .xlsx is read "
                     "with its skill's script; the command is given next to each attached file.")
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


def _restore(
    agent: Any, session_manager: Any, snapshot_id: str, instructions: str
) -> None:
    """Restore a snapshot, then re-apply what the snapshot may have overridden.

    The snapshot's stored `system_prompt` wins over the one passed to
    `create_harness`, so the prompt is set again afterwards. Without this, an
    edited prompt would have no effect on any chat that already has history.

    The prompt is **recomposed** with `build_system_prompt`, the harness's own
    function: assigning our text raw dropped the harness guidance, leaving only
    our text on the first restored turn.
    """
    async def _do() -> bool:
        return await session_manager.restore_snapshot(
            agent, snapshot_id=snapshot_id
        )

    ok = _run(_do())
    if not ok:
        raise ValueError(
            f"restore_snapshot({snapshot_id}) failed. The id is unknown, or the "
            "snapshot file was pruned. Retrying is not possible; the chat tree "
            "points at a snapshot that does not exist."
        )
    agent.system_prompt = _harness_prompt(instructions)


def _harness_prompt(instructions: str) -> str:
    """The harness prompt with our instructions appended, as the harness would.

    Returns an empty string when there is nothing to append, which leaves the
    agent on the harness default.
    """
    if not instructions or not instructions.strip():
        return ""
    return str(build_system_prompt(instructions=instructions))


def _run(coro: Any) -> Any:
    """Run a coroutine from sync code, whether or not a loop is already running."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Called on a thread with a running loop: run in a private loop on another
    # thread. The server calls `build_agent` via `asyncio.to_thread`, so it
    # normally takes the `asyncio.run` path above.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = [
    "CONVERSATION_MANAGERS",
    "RetryPlan",
    "build_agent",
    "build_conversation_manager",
    "build_model",
    "clock_note",
    "retry_hint",
]