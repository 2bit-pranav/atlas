"""
build_agent: the one place that calls create_harness (agent/AGENTS.md).

Everything above this file resolves settings into managers; this file asks the
managers for their parts, assembles one Strands Agent, and returns it. Tests
build an agent from here without a server.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from strands_harness import build_system_prompt, create_harness

from agent.core import paths
from agent.core.memory_manager import MemoryManager
from agent.core.shell_env import default_environment, model_path
from agent.core.model import AtlasLlamaCppModel
from agent.core.approvals import Approver, InstallApproval
from agent.core.documents import DocumentGuard, document_tools
from agent.core.resilience import LocalModelRetry, ToolFailureRecovery
from agent.core.session_manager import SessionManager
from agent.core.settings import Settings
from agent.core.skill_manager import SkillManager
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
        enable_thinking=thinking,
        context_window_limit=settings.context.window or settings.model.context_size,
        params=params,
        # Timings on every chunk, so the context meter and tokens/s move while
        # the answer is still being written rather than jumping at the end.
        extra_body={"timings_per_token": True},
        observer=observer,
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

    `NullConversationManager` is the honest default: the harness's
    `context_manager` is disabled (see `MemoryManager`), and until context trimming is measured
    one, keeping the full history is better than trimming with an untested rule.
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

    An earlier version of this claimed a bare `python` was not on PATH. That was
    true while the harness shelled out to `sh` and became false the moment the
    Windows environment ran commands through `cmd /c` -- and a confidently wrong
    instruction is worse than none, because a model will try to reconcile the
    two and lose a turn doing it.

    What is actually true, and what still needs saying:

    * `python` resolves to the project's own interpreter, because the Windows
      environment puts the venv's `Scripts` directory first on PATH. So the
      commands written in every `SKILL.md` work exactly as printed.
    * Never install anything. A missing library is reported to the user rather
      than installed, because a `pip install` from the model writes to user
      site-packages and leaves the environment quietly diverged from the
      project. This one is still needed as an instruction: it is a rule, not a
      fact, and rules do not follow from the PATH.

    Generated here rather than written into settings.json so it cannot drift
    from the interpreter that is actually running.
    """
    import sys

    workspace = paths.chat_dir(settings, chat_id)
    return (
        "Running things on this machine:\n"
        f"- Python: `{sys.executable}`, and a bare `python` resolves to the "
        f"same interpreter. Either works.\n"
        f"- Skill scripts live under `{model_path(paths.skills_dir(settings))}`, as "
        "`<skill>/scripts/<script>.py`. Run them by that full path.\n"
        "- Write every path exactly as given here, with forward slashes. "
        "Backslashes break in this shell.\n"
        f"- Your workspace for this chat is `{model_path(workspace)}`. Uploaded files are "
        "there, and any file you create goes there unless the user names "
        "another place.\n"
        "- You may install what a task needs (`python -m pip install ...` for "
        "Python packages, so they go into Atlas's own environment; `npm install "
        "-g ...` for Node tools). The user is asked to approve every install "
        "first; if they decline, do not try another way."
    )


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
    sandbox: Any = None,
) -> Any:
    """Build one Strands `Agent` for one turn.

    Args:
        restore_snapshot_id: rewind to this snapshot before returning. The
            agent is built empty and then restored, never the other way round.
        tools: extra tools (MCP) added beside the built-ins.
        retry: set on a retried turn, to widen sampling.
        observer: receives model-call stats and retry notices for the run.
        approver: asks the user before an install runs. Without one, installs
            are refused with an explanation.
    """
    tool_manager = ToolManager(settings)
    memory_manager = MemoryManager(settings)
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
        sandbox=sandbox if sandbox is not None else default_environment(),
        instructions=instructions or None,
        session=session_manager,
        skills=[s["path"] for s in skills] or False,
        interventions=tool_manager.interventions(),
        tools=[*tool_manager.extra_tools(), *atlas_tools, *(tools or [])],
        builtin_tools=builtin,
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
        hooks=[ToolFailureRecovery(settings.resilience), DocumentGuard(), InstallApproval(approver)],
    )

    if restore_snapshot_id:
        _restore(agent, session_manager, restore_snapshot_id, instructions)

    return agent


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

    Order matters: the snapshot's stored
    `system_prompt` wins over the one passed to `create_harness`, so the prompt
    is set again afterwards. Without this, editing the prompt in settings.json
    silently stops having any effect on every chat that already has history.

    The replacement is **recomposed**, not the settings string assigned raw.
    Assigning `settings.system_prompt` directly drops Strands' harness guidance
    -- caught by a test that showed the prompt collapsing to our text alone on
    the first restored turn. `build_system_prompt` is the same function the
    harness uses, so the extension stays an extension.
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
    # Inside a loop: run in a private one on another thread. The executor calls
    # this from a worker thread, so the two-thread case is the normal one.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = [
    "CONVERSATION_MANAGERS",
    "RetryPlan",
    "build_agent",
    "build_conversation_manager",
    "build_model",
    "retry_hint",
]