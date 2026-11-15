"""What Atlas assumes about Strands and the harness, pinned.

Each of these is a behaviour of the library, not of Atlas, that Atlas's code
depends on. A Strands update that changes one should fail here, not quietly in
a chat. The model is a script: no GPU, no llama-server.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers import settings_file
from strands.models import Model

from agent.config.settings import load_settings
from agent.runtime.factory import build_agent
from agent.store.snapshots import SessionManager


class ScriptedModel(Model):
    """A Strands model that streams one reply: reasoning, then text."""

    def __init__(self, reasoning: str = "Plan: answer briefly.", text: str = "Hello.") -> None:
        self.reasoning, self.text = reasoning, text
        self.config: dict[str, Any] = {}

    def update_config(self, **kw: Any) -> None:
        self.config.update(kw)

    def get_config(self) -> dict[str, Any]:
        return self.config

    async def structured_output(self, *a: Any, **kw: Any):  # pragma: no cover - never called
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        for part in (self.reasoning[:5], self.reasoning[5:]):
            yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": part}}}}
        yield {"contentBlockStop": {}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": self.text}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


@pytest.fixture
def settings(tmp_path):
    return load_settings(settings_file(tmp_path))


def _agent(settings, chat: str = "c1", **kw):
    agent = build_agent(settings, chat_id=chat, **kw)
    agent.model = ScriptedModel()
    return agent


def test_the_four_switches_keep_memory_and_its_tools_out(settings) -> None:
    names = set(_agent(settings).tool_names)
    assert not names & {"retrieve_context", "strands_manage_background_task", "todo_write", "memory"}
    assert "run_skill" in names and "shell" not in names        # the shell is off by default


def test_the_hook_events_have_the_fields_atlas_sets() -> None:
    from strands.hooks.events import AfterInvocationEvent, BeforeModelCallEvent, BeforeToolCallEvent

    assert "resume" in AfterInvocationEvent.__dataclass_fields__            # done_check, tool_recovery
    assert "cancel" in BeforeModelCallEvent.__dataclass_fields__            # limits
    assert {"cancel_tool", "selected_tool", "tool_use"} <= set(BeforeToolCallEvent.__dataclass_fields__)  # policy


def test_reasoning_arrives_once_in_the_saved_message(settings) -> None:
    agent = _agent(settings)
    agent("hi")
    last = agent.messages[-1]
    reasoning = [b for b in last["content"] if "reasoningContent" in b]
    assert len(reasoning) == 1
    assert reasoning[0]["reasoningContent"]["reasoningText"]["text"] == "Plan: answer briefly."
    assert [b["text"] for b in last["content"] if "text" in b] == ["Hello."]


def test_the_cancel_signal_is_a_threading_event_cleared_after_a_turn(settings) -> None:
    agent = _agent(settings)
    assert isinstance(agent.cancel_signal, threading.Event)   # tools poll it (pipelines, run_skill)
    agent("hi")
    assert not agent.cancel_signal.is_set()


def test_no_latest_snapshot_and_the_prompt_is_set_again_after_a_restore(settings, tmp_path) -> None:
    session = SessionManager(settings, "c1")
    manager = session.manager()
    agent = _agent(settings, session_manager=manager)
    agent("hi")
    snap = asyncio.run(manager.save_snapshot(agent, is_latest=False))
    assert not any("latest" in p.name for p in Path(session.storage_dir()).rglob("*"))

    settings.system_prompt = "Always answer in French."
    restored = _agent(settings, session_manager=session.manager(), restore_snapshot_id=snap)
    assert len(restored.messages) == 2                                      # the history came back
    assert "Always answer in French." in restored.system_prompt             # the snapshot's old prompt did not win
