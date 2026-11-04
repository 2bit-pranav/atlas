"""Workers (agent/runtime/workers.py): what a delegate shares with its parent and what it does not."""

from __future__ import annotations

import json
from pathlib import Path

from agent.config.settings import load_settings
from agent.model.sampling import build_model
from agent.recovery.tool_recovery import ToolFailureRecovery
from agent.runtime.factory import build_conversation_manager
from agent.runtime.workers import worker_tool
from agent.safety.limits import RunLimits
from agent.safety.policy import ToolPolicy
from agent.safety.scope import Scope

ROOT = Path(__file__).resolve().parents[1]


def _hook_owners(agent) -> set:
    """Every hook object registered on an agent (the instances behind its callbacks)."""
    return {getattr(e.callback, "__self__", None) for entries in agent.hooks._registered_callbacks.values()
            for e in entries}


def _child(tmp_path):
    raw = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    raw["paths"] = {"data_dir": str(tmp_path / "data")}
    (tmp_path / "s.json").write_text(json.dumps(raw), encoding="utf-8")
    settings = load_settings(tmp_path / "s.json")
    limits = RunLimits(settings.limits)
    policy = ToolPolicy(Scope(tmp_path / "ws"))
    recovery = ToolFailureRecovery(settings.resilience)
    tool = worker_tool(settings, model=build_model(settings, thinking=False, retry=None, observer=None),
                       builtin=["shell", "subagent"], builtin_extra={}, skills=False, interventions=None,
                       tools=[], hooks=[limits, policy, recovery], sandbox=None,
                       conversation_manager=lambda: build_conversation_manager(settings))
    child = tool._builder(tool._resolve({"task": "count to three"}))
    return child, limits, policy, recovery


def test_a_worker_runs_under_the_parents_policy_and_limits(tmp_path) -> None:
    child, limits, policy, recovery = _child(tmp_path)
    owners = _hook_owners(child)
    assert policy in owners                    # every tool call it makes is checked the same way
    assert limits in owners                    # its model calls count toward the message's limit
    assert recovery not in owners              # its own failure budget: sharing one let it wipe the parent's
    assert any(isinstance(h, ToolFailureRecovery) for h in owners)


def test_a_worker_keeps_no_history_prints_nothing_and_cannot_delegate(tmp_path) -> None:
    from strands.handlers.callback_handler import null_callback_handler

    child, *_ = _child(tmp_path)
    assert child._session_manager is None      # nothing it does is written into the chat's history
    assert child.callback_handler is null_callback_handler
    assert "subagent" not in child.tool_registry.registry
    assert "shell" in child.tool_registry.registry
