"""Offline tests for the chat tree (agent/store/chats.py): send, retry, edit,
version switching and crash recovery."""

from __future__ import annotations

import pytest

from agent.store.chats import ChatStore, TreeError


@pytest.fixture
def store(tmp_path):
    s = ChatStore(tmp_path / "atlas.db")
    yield s
    s.close()


def _turn(store: ChatStore, chat: str, text: str, parent: str | None, snap: str | None = None) -> str:
    turn = store.insert_turn(chat, text, parent_turn_id=parent, before_snap=snap)
    store.finish_turn(turn["id"], "completed", after_snap=f"snap-{text}")
    return turn["id"]


def _texts(store: ChatStore, chat: str) -> list[str]:
    return [t["user_text"] for t in store.path(chat)]


def test_messages_follow_each_other(store) -> None:
    chat = store.create_chat()["id"]
    a = _turn(store, chat, "a", None)
    b = _turn(store, chat, "b", a, "snap-a")
    assert _texts(store, chat) == ["a", "b"]
    assert store.leaf(chat)["id"] == b and store.is_leaf(b) and not store.is_leaf(a)


def test_a_retry_is_a_sibling_and_becomes_selected(store) -> None:
    chat = store.create_chat()["id"]
    a = _turn(store, chat, "a", None)
    b1 = _turn(store, chat, "b", a)
    b2 = _turn(store, chat, "b-retry", a)
    assert [t["id"] for t in store.siblings_of(b1)] == [b1, b2]
    assert _texts(store, chat) == ["a", "b-retry"]
    store.select(b1)                                   # the "<" button
    assert _texts(store, chat) == ["a", "b"]


def test_each_version_keeps_its_own_follow_ups(store) -> None:
    chat = store.create_chat()["id"]
    a = _turn(store, chat, "a", None)
    b1 = _turn(store, chat, "b", a)
    _turn(store, chat, "c-under-b", b1)
    b2 = _turn(store, chat, "b2", a)
    _turn(store, chat, "c-under-b2", b2)
    store.select(b1)
    assert _texts(store, chat) == ["a", "b", "c-under-b"]
    store.select(b2)
    assert _texts(store, chat) == ["a", "b2", "c-under-b2"]


def test_edit_cuts_every_version_and_everything_below(store) -> None:
    chat = store.create_chat()["id"]
    a = _turn(store, chat, "a", None)
    b1 = _turn(store, chat, "b", a, "snap-a")
    c = _turn(store, chat, "c", b1)
    b2 = _turn(store, chat, "b2", a, "snap-a")
    cut, snaps = store.cut_from(b1)
    assert cut["id"] == b1 and cut["before_snap"] == "snap-a"
    assert sorted(snaps) == sorted(["snap-b", "snap-c", "snap-b2"])
    assert "snap-a" not in snaps                       # still the parent's
    assert all(store.get_turn(t) is None for t in (b1, c, b2))
    assert _texts(store, chat) == ["a"]


def test_editing_the_first_message_empties_the_chat(store) -> None:
    chat = store.create_chat()["id"]
    a = _turn(store, chat, "a", None)
    _turn(store, chat, "b", a)
    store.cut_from(a)
    assert store.path(chat) == []


def test_running_turns_become_interrupted_after_a_crash(store) -> None:
    chat = store.create_chat()["id"]
    store.insert_turn(chat, "left running", parent_turn_id=None, before_snap=None)
    assert store.mark_interrupted() == 1
    assert store.leaf(chat)["status"] == "interrupted"


def test_unknown_turns_and_statuses_are_refused(store) -> None:
    with pytest.raises(TreeError):
        store.select("nope")
    with pytest.raises(TreeError):
        store.cut_from("nope")
    chat = store.create_chat()["id"]
    turn = store.insert_turn(chat, "x", parent_turn_id=None, before_snap=None)
    with pytest.raises(ValueError):
        store.finish_turn(turn["id"], "half-done")


def test_delete_chat_returns_its_snapshots(store) -> None:
    chat = store.create_chat()["id"]
    a = _turn(store, chat, "a", None)
    _turn(store, chat, "b", a)
    assert sorted(store.delete_chat(chat)) == ["snap-a", "snap-b"]
    assert store.get_chat(chat) is None and store.path(chat) == []
