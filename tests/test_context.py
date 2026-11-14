"""Earlier tool results shortened near the window (agent/runtime/context.py, plan 3.9)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.runtime.context import TrimToolResults, trim


def _turn(n: int, size: int) -> list[dict]:
    """One earlier turn: the question, a tool call, its result, the answer."""
    return [{"role": "user", "content": [{"text": f"question {n}"}]},
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": f"t{n}", "name": "read_pdf", "input": {}}}]},
            {"role": "user", "content": [{"toolResult": {"toolUseId": f"t{n}", "status": "success",
                                                         "content": [{"text": "x" * size}]}}]},
            {"role": "assistant", "content": [{"text": f"answer {n}: the figure is {n}00"}]}]


def _result(messages: list[dict], n: int) -> str:
    return messages[4 * n + 2]["content"][0]["toolResult"]["content"][0]["text"]


def test_old_results_go_oldest_first_and_the_answers_and_the_current_turn_stay() -> None:
    messages = _turn(0, 30_000) + _turn(1, 30_000) + _turn(2, 30_000)
    assert trim(messages, 70_000) == 1
    assert _result(messages, 0).startswith("[Earlier result of read_pdf, 30,000 characters")
    assert _result(messages, 1) == "x" * 30_000
    assert [m["content"][0]["text"] for m in messages[3::4]] == ["answer 0: the figure is 000",
                                                                 "answer 1: the figure is 100", "answer 2: the figure is 200"]
    assert trim(messages, 0) == 1 and _result(messages, 2) == "x" * 30_000      # turn 2 is the current turn


def test_nothing_changes_under_the_trigger() -> None:
    manager = TrimToolResults(32768, 0.75, 0.5)
    agent = SimpleNamespace(messages=_turn(0, 30_000) + _turn(1, 30_000))
    before = repr(agent.messages)
    manager.apply_management(agent)
    assert repr(agent.messages) == before            # llama.cpp's cached prefix survives
    agent.messages += _turn(2, 40_000)
    manager.apply_management(agent)
    assert _result(agent.messages, 0).startswith("[Earlier result")


def test_an_overflow_with_nothing_left_to_trim_is_raised() -> None:
    agent = SimpleNamespace(messages=_turn(0, 100))
    with pytest.raises(ValueError):
        TrimToolResults(32768, 0.75, 0.5).reduce_context(agent, ValueError("too long"))

