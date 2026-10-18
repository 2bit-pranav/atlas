"""`build_agent`: the one place that calls `create_harness` (design.md 1a).

Everything above this file resolves settings into managers; this file asks the
managers for their parts, assembles one Strands `Agent`, and returns it. Tests
build an agent from here without a server.

**A fresh agent per turn**, for one reason: LIVE settings must apply on the
next turn with no restart. There is no other way to guarantee that.

Three things in here were found by measuring rather than reading docs, and each
is load-bearing:

1. **The system prompt is set AFTER the restore.** A snapshot stores its
   `system_prompt`, and after `restore_snapshot` the *stored* prompt beats the
   one just passed in. So editing the prompt in `settings.json` would silently
   never apply to any chat that already has snapshots -- the settings change,
   the model does not, and nothing errors. (T3.8)

2. **Four switches, not one, keep memory off.** `memory=False` alone still
   leaves `strands_manage_background_task` in the request, along with
   `retrieve_context`, `search_memory` and `todo_write`. The documented
   shutdown was incomplete. (T0.5)

3. **Restoring an older snapshot is not enough on its own.** After restore, the
   agent also needs its prompt, its invocation state and a clean conversation
   manager, or the next turn sees a mixture of two histories.
"""

from __future__ import annotations

import logging
from typing import Any

from strands_harness import build_system_prompt, create_harness

from agent.core.memory_manager import MemoryManager
from agent.core.shell_env import default_environment
from agent.core.model import AtlasLlamaCppModel
from agent.core.session_manager import SessionManager
from agent.core.settings import Settings
from agent.core.skill_manager import SkillManager
from agent.core.tool_manager import ToolManager

logger = logging.getLogger(__name__)

#: Conversation managers by `context.conversation_manager`. L6 picks one of
#: these; `null` is the default because the harness's own context manager is a
#: leak vector and no SDK manager has been measured against a 32k local model.
CONVERSATION_MANAGERS = {
    "null": "NullConversationManager",
    "sliding": "SlidingWindowConversationManager",
    "summarizing": "SummarizingConversationManager",
}


def build_model(settings: Settings, *, thinking: bool) -> AtlasLlamaCppModel:
    """The model for this turn.

    Sampling comes from settings every time, so a temperature change applies to
    the next turn rather than after a restart.
    """
    s = settings.sampling
    params: dict[str, Any] = {
        "cache_prompt": True,
        "temperature": s.temperature,
        "top_p": s.top_p,
        "top_k": s.top_k,
        "repeat_penalty": s.repeat_penalty,
    }
    if s.max_tokens:
        params["max_tokens"] = s.max_tokens
    if s.presence_penalty:
        params["presence_penalty"] = s.presence_penalty
    if s.frequency_penalty:
        params["frequency_penalty"] = s.frequency_penalty

    return AtlasLlamaCppModel(
        base_url=f"http://127.0.0.1:{settings.ports.llama}",
        enable_thinking=thinking,
        context_window_limit=settings.context.window or settings.model.context_size,
        params=params,
    )


def build_conversation_manager(settings: Settings) -> Any:
    """The SDK conversation manager named in settings, or Null.

    `NullConversationManager` is the honest default: the harness's
    `context_manager` is disabled (see `MemoryManager`), and until L6 measures
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


def _runtime_facts() -> str:
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

    return (
        "Running things on this machine:\n"
        f"- Python: `{sys.executable}`, and a bare `python` resolves to the "
        f"same interpreter. Either works.\n"
        "- Skill scripts live under `skills/<name>/scripts/`; run them from "
        "the application root, as `python skills/<name>/scripts/<script>.py "
        "<args>`.\n"
        "- NEVER run pip, pip install, conda, or any other installer. If a "
        "script reports a missing library, that is a setup problem to tell the "
        "user about, not something to fix. Installing from here puts packages "
        "somewhere the scripts will not find them."
    )


def build_agent(
    settings: Settings,
    *,
    chat_id: str,
    thinking: bool = False,
    restore_snapshot_id: str | None = None,
    session_manager: Any = None,
    tools: list | None = None,
    extra_instructions: str = "",
    sandbox: Any = None,
) -> Any:
    """Build one Strands `Agent` for one turn.

    Args:
        restore_snapshot_id: rewind to this snapshot before returning. The
            agent is built empty and then restored, never the other way round.
        extra_instructions: appended to the user turn *outside* the snapshot,
            so repeated retries cannot compound it. Used by regeneration.
    """
    tool_manager = ToolManager(settings)
    memory_manager = MemoryManager(settings)
    skill_manager = SkillManager(settings)

    if session_manager is None:
        session_manager = SessionManager(settings, chat_id).manager()

    model = build_model(settings, thinking=thinking)

    # settings.system_prompt is an *extension*: `instructions=` appends to the
    # harness prompt, so the harness guidance is always retained. Measured at
    # 1665 -> 1700 chars with our text added (T3.8).
    instructions = _compose_instructions(settings.system_prompt, extra_instructions)

    agent = create_harness(
        model=model,
        # The stock environment shells out to `sh`, which does not exist on
        # Windows, so every shell call failed with WinError 2. Passed here
        # because `sandbox=` is the documented seam; the shell tool picks it
        # up from `agent.sandbox` with no other change.
        sandbox=sandbox if sandbox is not None else default_environment(),
        instructions=instructions or None,
        session=session_manager,
        skills=skill_manager.harness_skills(),
        interventions=tool_manager.interventions(),
        tools=tools if tools is not None else tool_manager.extra_tools(),
        builtin_tools=tool_manager.builtin_tools(),
        # The four off-switches, together. Any one of them alone is not enough.
        **memory_manager.harness_args(),
        conversation_manager=build_conversation_manager(settings),
        caching=False,
    )

    if restore_snapshot_id:
        _restore(agent, session_manager, restore_snapshot_id, instructions)

    return agent


def _compose_instructions(system_prompt: str, extra: str) -> str:
    parts = [p.strip() for p in (system_prompt, extra) if p and p.strip()]
    parts.append(_runtime_facts())
    return "\n\n".join(parts)


def _restore(
    agent: Any, session_manager: Any, snapshot_id: str, instructions: str
) -> None:
    """Restore a snapshot, then re-apply what the snapshot may have overridden.

    Order matters and is the whole point of T3.8: the snapshot's stored
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
    "build_agent",
    "build_conversation_manager",
    "build_model",
]