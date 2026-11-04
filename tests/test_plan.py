"""The plan check (agent/runtime/plan.py): finish the plan, and a plan per message."""

from __future__ import annotations

from types import SimpleNamespace

from agent.runtime.plan import STATE_KEY, PlanCheck


class _State(dict):
    def set(self, key, value):
        self[key] = value

    def delete(self, key):
        self.pop(key, None)


def _agent(todos):
    state = _State()
    if todos is not None:
        state[STATE_KEY] = todos
    return SimpleNamespace(state=state)


def _end(agent, stop="end_turn"):
    return SimpleNamespace(agent=agent, result=SimpleNamespace(stop_reason=stop), resume=None)


def _item(text, status):
    return {"content": text, "activeForm": text, "status": status}


def test_ending_with_steps_open_is_sent_back_once_naming_them() -> None:
    notes = []
    check = PlanCheck(notify=notes.append)
    agent = _agent([_item("Read v1", "completed"), _item("Compare them", "pending")])
    event = _end(agent)
    check._after(event)
    assert "- Compare them" in event.resume and "Read v1" not in event.resume
    assert notes == [{"type": "resumed", "reason": "plan not finished"}]
    again = _end(agent)
    check._after(again)
    assert again.resume is None                               # once: never a loop


def test_a_finished_plan_or_another_stop_is_left_alone() -> None:
    done = _end(_agent([_item("Read v1", "completed")]))
    PlanCheck()._after(done)
    assert done.resume is None
    limited = _end(_agent([_item("Compare", "pending")]), stop="cancelled")   # a limit or Stop
    PlanCheck()._after(limited)
    assert limited.resume is None
    taken = _end(_agent([_item("Compare", "pending")]))
    taken.resume = "another hook's resume"
    PlanCheck()._after(taken)
    assert taken.resume == "another hook's resume"


def test_a_new_message_starts_without_the_last_finished_plan() -> None:
    finished = _agent([_item("Read v1", "completed")])
    PlanCheck()._before(SimpleNamespace(agent=finished))
    assert STATE_KEY not in finished.state
    unfinished = _agent([_item("Compare", "pending")])
    PlanCheck()._before(SimpleNamespace(agent=unfinished))
    assert STATE_KEY in unfinished.state                      # "continue" picks it up
