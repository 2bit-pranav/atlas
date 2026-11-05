"""
build_agent: the one place that calls create_harness (agent/AGENTS.md).

Each manager resolves its part of the settings; this file asks them for their
parts and assembles one Strands Agent per turn, so a LIVE setting applies to
the next message. It needs no server.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from strands_harness import create_harness

from agent.config import paths
from agent.config.settings import Settings
from agent.ingest.store import store_for
from agent.integrations.skills.catalog import SkillManager
from agent.model.sampling import RetryPlan, build_model
from agent.platform.windows_shell import WindowsLocalEnvironment, default_environment
from agent.platform.winpaths import shown_in
from agent.prompt.system import _compose_instructions, _tool_sources
from agent.recovery.model_retry import LocalModelRetry
from agent.recovery.tool_recovery import ToolFailureRecovery
from agent.runtime.memory import MemoryManager
from agent.runtime.restore import _restore
from agent.runtime.skill_tools import SkillTools
from agent.safety.approvals import Approver
from agent.safety.limits import RunLimits
from agent.safety.policy import TaintTracker, ToolPolicy
from agent.safety.protected import Protected
from agent.safety.scope import Scope
from agent.store.snapshots import SessionManager
from agent.tools.doc_reading import doc_read_tools
from agent.tools.documents.tool import document_tools
from agent.tools.files import file_tools
from agent.tools.finding import finding_tools
from agent.tools.manager import ToolManager
from agent.tools.maths.tool import maths_tools
from agent.tools.reading import read_tools
from agent.tools.web import read_key, web_tools

CONVERSATION_MANAGERS = {
    "null": "NullConversationManager",
    "sliding": "SlidingWindowConversationManager",
    "summarizing": "SummarizingConversationManager",
}


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
    chat_grants: list | None = None,
    tainted: Callable[[], bool] | None = None,
    untrusted: Callable[[str], bool] | None = None,
    on_taint: Callable[[], None] | None = None,
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
        sensitive: whether a tool, by its agent-facing name, must ask first.
        chat_grants: the chat's "Allow for this chat" answers, kept across turns.
        tainted: whether outside content (a web page, a fetch) has entered the chat.
        untrusted: whether an MCP tool, by its agent-facing name, returns outside content.
        on_taint: called when a tool brings outside content in (`TaintTracker`).
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
    enabled = set(tool_manager.atlas_tools())
    scope = _scope(settings, workspace_dir)
    # The tools place a path exactly as the policy checks it: one rule (Scope.place).
    resolve = scope.place
    shown = shown_in(workspace_dir)
    store = store_for(paths.data_dir(settings))
    atlas_tools = [t for t in (*finding_tools(scope, resolve, shown, store),
                               *read_tools(resolve, shown, settings.model.supports_vision),
                               *doc_read_tools(store, chat_id, resolve, workspace_dir, on_taint),
                               *file_tools(resolve, shown),
                               # Not offered without a key: a tool that only fails wastes a turn.
                               *(web_tools(paths.data_dir(settings)) if read_key(paths.data_dir(settings)) else []),
                               *maths_tools())
                   if t.tool_name in enabled]
    # Writing tools are registered when their skill is loaded (runtime/skill_tools.py).
    skill_tools = SkillTools({name: t for name, t in document_tools(
        workspace_dir, shown, resolve, store, chat_id).items() if name in enabled})
    instructions = _compose_instructions(settings, chat_id, _tool_sources(
        [*builtin, *(t.tool_name for t in atlas_tools)], [s["name"] for s in skills], list(tools or [])))

    agent = create_harness(
        model=model,
        # The stock environment shells out to `sh`, which does not exist on
        # Windows. `sandbox=` is the documented seam; the shell tool picks it
        # up from `agent.sandbox` with no other change.
        sandbox=sandbox if sandbox is not None else default_environment(
            cwd=paths.chat_dir(settings, chat_id), skills=paths.skills_dir(settings),
            folders=scope.folders),
        instructions=instructions or None,
        session=session_manager,
        skills=[s["path"] for s in skills] or False,
        interventions=tool_manager.interventions(),
        tools=[*tool_manager.extra_tools(), *atlas_tools, *(tools or [])],
        builtin_tools={"*": False, **{name: True for name in builtin}},
        # The four off-switches, together. Any one of them alone is not enough.
        **memory_manager.harness_args(),
        conversation_manager=build_conversation_manager(settings),
        caching=False,
        # Strands' default handler prints every streamed token to stdout. Under
        # `atlas start` that console is cp1252, so an emoji or an arrow in an
        # answer raised UnicodeEncodeError and failed the whole run. Atlas
        # reads the stream itself and never wants the printout.
        callback_handler=None,
        # Recovery is hooks, not prompt text: see agent/recovery/.
        retry_strategy=LocalModelRetry(settings.resilience, notify=observer),
        # Before a tool runs: the run's limits, then one ordered policy
        # (policy.py), so a refused repeat never shows a card. After: recovery.
        hooks=[RunLimits(settings.limits, notify=observer),
               ToolPolicy(scope, approver=approver,
                          ask_outside=settings.access.ask_outside, sensitive=sensitive, tainted=tainted,
                          mode=settings.access.mode, chat_grants=chat_grants),
               ToolFailureRecovery(settings.resilience, notify=observer),
               skill_tools,
               *([TaintTracker(untrusted or (lambda _name: False), on_taint)] if on_taint else [])],
    )

    if isinstance(agent.sandbox, WindowsLocalEnvironment):
        agent.sandbox.cancel_signal = agent.cancel_signal  # Stop ends a running command too
    if restore_snapshot_id:
        _restore(agent, session_manager, restore_snapshot_id, instructions)
    skill_tools.sync(agent)  # the skills earlier turns loaded bring their tools again

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
        protected=Protected(root=paths.ROOT, data=paths.data_dir(settings),
                            mcp_config=paths.mcp_config(settings), venv=Path(sys.prefix),
                            skills=paths.skills_dir(settings), workspace=workspace),
    )


__all__ = ["CONVERSATION_MANAGERS", "build_agent", "build_conversation_manager"]
