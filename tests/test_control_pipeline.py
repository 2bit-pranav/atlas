"""Regression tests for Atlas-owned run and chat-tree control state.

These do not need a model server. They protect the rules that must hold before
Strands is invoked: one active run, no mutation on a rejected start, and a
root-version selection that actually changes the visible path.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent.core.chats import ChatStore, COMPLETED
from server.app import create_app
from server.runs import RunConflict, RunManager


def test_root_version_selection_changes_visible_path(tmp_path) -> None:
    store = ChatStore(tmp_path / "atlas.db")
    chat = store.create_chat()

    first = store.insert_turn(
        chat["id"], "first", parent_turn_id=None, before_snap=None
    )
    store.set_status(first["id"], COMPLETED, after_snap="first-snapshot")

    replacement = store.insert_turn(
        chat["id"], "replacement", parent_turn_id=None, before_snap=None
    )
    store.set_status(replacement["id"], COMPLETED, after_snap="replacement-snapshot")

    assert store.leaf(chat["id"])["id"] == replacement["id"]
    store.select_root(chat["id"], first["id"])
    assert [turn["id"] for turn in store.path(chat["id"])] == [first["id"]]


def test_active_run_rejection_happens_before_turn_creation() -> None:
    runs = RunManager()
    runs.start("chat-a", "turn-a")

    try:
        runs.ensure_available()
    except RunConflict:
        pass
    else:  # pragma: no cover - makes a false negative explicit
        raise AssertionError("an active run must reserve the single run slot")


def test_rejected_send_does_not_create_a_running_turn(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    app = create_app(settings_path=root / "settings.json", root=tmp_path)
    client = TestClient(app)
    chat_id = client.post("/chats").json()["id"]

    # Reserve the global slot without building an agent or needing llama-server.
    app.state.atlas.runs.start("another-chat", "another-turn")
    response = client.post(f"/chats/{chat_id}/messages", json={"text": "hello"})

    assert response.status_code == 409
    assert app.state.atlas.store.path(chat_id) == []
