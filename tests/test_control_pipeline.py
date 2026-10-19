"""Offline tests for the rules Atlas owns. No model server needed.

    python -m pytest tests/test_control_pipeline.py

`tests/live_api.py` covers the same rules end to end against the real model.
"""

from __future__ import annotations

import json

from agent.core.chats import COMPLETED, ChatStore
from agent.core.resilience import _is_empty, _nonzero_exit
from agent.core.settings import changed_restart_keys, load_settings, restart_tier_values
from server.runs import RunConflict, RunManager
from server.transcript import Transcript


def _completed(store: ChatStore, chat: str, text: str, parent: str | None, snap: str) -> str:
    turn = store.insert_turn(chat, text, parent_turn_id=parent,
                             before_snap=None if parent is None else f"after-{parent}")
    store.finish_turn(turn["id"], COMPLETED, after_snap=snap)
    return turn["id"]


def test_retry_siblings_keep_their_own_followups(tmp_path) -> None:
    store = ChatStore(tmp_path / "atlas.db")
    chat = store.create_chat()["id"]
    a1 = _completed(store, chat, "q1", None, "s-a1")
    a2 = _completed(store, chat, "q1", None, "s-a2")          # retry of the root
    b = _completed(store, chat, "q2", a2, "s-b")
    assert [t["id"] for t in store.path(chat)] == [a2, b]
    store.select(a1)
    assert [t["id"] for t in store.path(chat)] == [a1]       # v1's branch ends there
    store.select(a2)
    assert [t["id"] for t in store.path(chat)] == [a2, b]    # v2 keeps its follow-up


def test_edit_cuts_versions_and_everything_below(tmp_path) -> None:
    store = ChatStore(tmp_path / "atlas.db")
    chat = store.create_chat()["id"]
    root = _completed(store, chat, "q1", None, "s-root")
    k1 = _completed(store, chat, "q2", root, "s-k1")
    k2 = _completed(store, chat, "q2", root, "s-k2")
    below = _completed(store, chat, "q3", k2, "s-below")
    old, snaps = store.cut_from(k1)
    assert old["parent_turn_id"] == root
    assert sorted(snaps) == ["s-below", "s-k1", "s-k2"]
    assert "s-root" not in snaps                              # the restore point survives
    assert store.get_turn(below) is None and store.get_turn(k2) is None
    assert [t["id"] for t in store.path(chat)] == [root]


def test_one_active_run() -> None:
    runs = RunManager()
    runs.start("chat", "turn")
    try:
        runs.start("chat", "turn-2")
    except RunConflict:
        return
    raise AssertionError("second run should be refused")


def test_restart_keys_compare_flat_to_nested() -> None:
    settings = load_settings("settings.json").model_dump(mode="json")
    flat = restart_tier_values(settings)
    assert changed_restart_keys(settings, flat) == {}
    flat["ports.llama"] = 1
    assert changed_restart_keys(settings, flat) == {"ports.llama": settings["ports"]["llama"]}


def test_transcript_drops_a_retried_model_call() -> None:
    t = Transcript(32768)
    t.fold({"type": "call_start"})
    t.fold({"type": "text_delta", "text": "half an ans"})
    t.fold({"type": "model_retry"})
    t.fold({"type": "call_start"})
    t.fold({"type": "thinking_delta", "text": "hm"})
    t.fold({"type": "text_delta", "text": "full "})
    t.fold({"type": "text_delta", "text": "answer"})
    assert t.parts == [{"kind": "reasoning", "text": "hm"}, {"kind": "text", "text": "full answer"}]


def test_failure_detection() -> None:
    bad = {"status": "success", "content": [{"text": json.dumps({"output": "", "exit_code": 2})}]}
    good = {"status": "success", "content": [{"text": json.dumps({"output": "x", "exit_code": 0})}]}
    assert _nonzero_exit(bad) and not _nonzero_exit(good)
    assert _is_empty({"content": [{"reasoningContent": {}}, {"text": "  "}]})
    assert not _is_empty({"content": [{"toolUse": {}}]})


def test_resume_supersedes_the_answer_given_up_on() -> None:
    t = Transcript(32768)
    t.fold({"type": "text_delta", "text": "I could not read the file."})
    t.fold({"type": "resumed", "reason": "tool failure"})
    t.fold({"type": "text_delta", "text": "The apparatus is Packet Tracer."})
    assert [p["kind"] for p in t.parts] == ["superseded", "text"]
    assert t.answer_text() == "The apparatus is Packet Tracer."


def test_markdown_images_become_blocks() -> None:
    from agent.core.documents import parse_markdown

    kinds = [b.kind for b in parse_markdown("# T\n\n![fig](a.png)\n\ntext ![i](b.png) more\n")]
    assert kinds == ["heading", "image", "para", "image"]
