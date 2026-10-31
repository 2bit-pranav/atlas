"""Plan item 6: every run has cheap limits (agent/safety/limits.py).

A small model can loop: the same call again and again, or model calls that
never end. Nothing stopped either but the user. Needed before anything runs
with nobody watching.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.config.settings import LimitsSettings
from agent.safety.limits import RunLimits


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _limits(**kw):
    seen: list[dict] = []
    clock = Clock()
    return RunLimits(LimitsSettings(**kw), notify=seen.append, clock=clock), seen, clock


def _model_call():
    return SimpleNamespace(cancel=False)


def _tool(name="shell", **args):
    return SimpleNamespace(tool_use={"name": name, "toolUseId": "t", "input": args}, cancel_tool=False)


def test_model_calls_stop_at_the_limit() -> None:
    limits, seen, _ = _limits(max_model_calls=3)
    events = [_model_call() for _ in range(5)]
    for e in events:
        limits.before_model_call(e)
    assert [bool(e.cancel) for e in events] == [False, False, False, True, True]
    assert "3 model calls" in events[3].cancel
    assert [s["type"] for s in seen] == ["limit"]        # told once, not on every refusal


def test_a_run_stops_after_its_time() -> None:
    limits, seen, clock = _limits(max_minutes=15)
    first = _model_call()
    limits.before_model_call(first)
    clock.now += 15 * 60 + 1
    late_tool, late_call = _tool(command="ls"), _model_call()
    limits.before_tool_call(late_tool)
    limits.before_model_call(late_call)
    assert not first.cancel
    assert late_tool.cancel_tool and "15 minutes" in late_tool.cancel_tool
    assert late_call.cancel and "15 minutes" in late_call.cancel


def test_the_same_call_past_the_limit_is_refused() -> None:
    limits, _, _ = _limits(repeat_limit=3)
    calls = [_tool(command="ls -la") for _ in range(4)]
    for c in calls:
        limits.before_tool_call(c)
    assert [bool(c.cancel_tool) for c in calls] == [False, False, False, True]
    assert "already" in calls[3].cancel_tool


def test_different_arguments_are_different_calls() -> None:
    limits, _, _ = _limits(repeat_limit=1)
    calls = [_tool(command="ls a"), _tool(command="ls b"), _tool(name="read", command="ls a")]
    for c in calls:
        limits.before_tool_call(c)
    assert not any(c.cancel_tool for c in calls)


def test_argument_order_does_not_hide_a_repeat() -> None:
    limits, _, _ = _limits(repeat_limit=1)
    a = SimpleNamespace(tool_use={"name": "read", "input": {"path": "x", "limit": 5}}, cancel_tool=False)
    b = SimpleNamespace(tool_use={"name": "read", "input": {"limit": 5, "path": "x"}}, cancel_tool=False)
    limits.before_tool_call(a)
    limits.before_tool_call(b)
    assert b.cancel_tool


def test_defaults() -> None:
    s = LimitsSettings()
    assert (s.max_model_calls, s.max_minutes, s.repeat_limit) == (40, 15, 3)
