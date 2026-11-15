"""A question asked by code (agent/runtime/model_call.py): Stop, the limits and the trace hold for it too."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.config.settings import LimitsSettings
from agent.runtime import model_call
from agent.runtime.model_call import ModelCall, ModelCallError, Stopped
from agent.safety.limits import RunLimits

SETTINGS = SimpleNamespace(model=SimpleNamespace(name="m"), ports=SimpleNamespace(llama=1))


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return {"choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
                "timings": {"prompt_n": 10, "predicted_n": 5}}


@pytest.fixture
def replies(monkeypatch):
    sent: list[dict] = []
    answers = ['{"x": 1}']

    def post(url, json, headers, timeout):
        sent.append(json)
        return _Reply(answers[min(len(sent), len(answers)) - 1])

    monkeypatch.setattr(model_call.httpx, "post", post)
    return sent, answers


def test_an_answer_is_parsed_and_traced(replies) -> None:
    sent, _ = replies
    events: list[dict] = []
    got = ModelCall(SETTINGS, observer=events.append).ask("q", {"type": "object"}, system="s", name="t")
    assert got == {"x": 1}
    assert sent[0]["response_format"]["json_schema"] == {"name": "t", "schema": {"type": "object"}}
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False} and "tools" not in sent[0]
    assert [e["type"] for e in events] == ["call_start", "model_request", "model_response", "call_timings"]


def test_stop_and_the_limits_hold(replies) -> None:
    sent, _ = replies
    with pytest.raises(Stopped):
        ModelCall(SETTINGS, cancelled=lambda: True).ask("q", {})
    limits = RunLimits(LimitsSettings(max_model_calls=2))
    call = ModelCall(SETTINGS, limits=limits)
    call.ask("q", {})
    call.ask("q", {})
    with pytest.raises(Stopped, match="2 model calls"):
        call.ask("q", {})
    assert len(sent) == 2                       # the third never reached the model


def test_a_cut_off_answer_is_an_error(replies) -> None:
    _, answers = replies
    answers[0] = '{"x": [1, 2'
    with pytest.raises(ModelCallError, match="cut off"):
        ModelCall(SETTINGS).ask("q", {})
