"""The page sent with a side-panel message (agent/prompt/page.py, Atlas._page_text): no tool call to read it."""

from __future__ import annotations

from types import SimpleNamespace

from agent.prompt.page import INLINE_CHARS, page_hash, page_note
from agent.store.chats import ChatStore
from agent.tools.page import UNTRUSTED
from server.state import Atlas

PAGE = {"url": "https://college.example/regulations", "title": "Academic Regulations",
        "kind": "article", "content": "# Attendance\nA student must have a minimum of 75% attendance. [Apply](e4)"}


def test_the_page_is_in_the_message_marked_as_data() -> None:
    note = page_note(PAGE)
    assert UNTRUSTED in note and "minimum of 75% attendance" in note
    assert note.index(UNTRUSTED) < note.index("<page>")              # the marking comes before the content
    assert 'page_show("e12")' in note and "exact quote" in note


def test_a_google_doc_and_a_selection_are_introduced_as_such() -> None:
    assert "The Google Doc's text:" in page_note({**PAGE, "kind": "document"})
    assert "around the passage the user selected" in page_note({**PAGE, "kind": "selection"})
    assert "attached to this message" in page_note({**PAGE, "kind": "drive-file", "content": ""})


def test_without_content_the_model_is_told_to_read_it() -> None:
    assert "Read it with page_read" in page_note({**PAGE, "content": ""})


def _atlas(store: ChatStore) -> SimpleNamespace:
    tainted: list[bool] = []
    fake = SimpleNamespace(store=store, tainted=tainted, taint=lambda run: tainted.append(True))
    fake._earlier_page_hashes = lambda turn: Atlas._earlier_page_hashes(fake, turn)  # type: ignore[arg-type]
    return fake


def _run(page: dict) -> SimpleNamespace:
    return SimpleNamespace(page=page, transcript=SimpleNamespace(stats={}))


def test_a_page_already_sent_in_the_chat_is_not_sent_again(tmp_path) -> None:
    store = ChatStore(tmp_path / "atlas.db")
    chat = store.create_chat("Regulations")["id"]
    first = store.insert_turn(chat, "what does it say?", parent_turn_id=None, before_snap=None)
    store.finish_turn(first["id"], "completed", stats={"page_hash": page_hash(PAGE["content"])})
    second = store.insert_turn(chat, "and for labs?", parent_turn_id=first["id"], before_snap=None)
    atlas, run = _atlas(store), _run(PAGE)
    note = Atlas._page_text(atlas, run, second, tmp_path)  # type: ignore[arg-type]
    assert "has not changed" in note and "<page>" not in note
    assert atlas.tainted and run.transcript.stats["page_hash"] == page_hash(PAGE["content"])
    changed = Atlas._page_text(atlas, _run({**PAGE, "content": PAGE["content"] + " Updated."}), second, tmp_path)  # type: ignore[arg-type]
    assert "<page>" in changed


def test_a_page_sent_with_a_failed_turn_is_sent_again(tmp_path) -> None:
    """A failed turn left no snapshot: the model never kept that page."""
    store = ChatStore(tmp_path / "atlas.db")
    chat = store.create_chat("x")["id"]
    first = store.insert_turn(chat, "q", parent_turn_id=None, before_snap=None)
    store.finish_turn(first["id"], "failed", stats={"page_hash": page_hash(PAGE["content"])})
    second = store.insert_turn(chat, "again", parent_turn_id=first["id"], before_snap=None)
    assert "<page>" in Atlas._page_text(_atlas(store), _run(PAGE), second, tmp_path)  # type: ignore[arg-type]


def test_a_long_page_goes_to_a_file_with_its_start_inline(tmp_path) -> None:
    store = ChatStore(tmp_path / "atlas.db")
    turn = store.insert_turn(store.create_chat("x")["id"], "q", parent_turn_id=None, before_snap=None)
    long = {**PAGE, "content": "\n".join(f"Line {i} of the regulations." for i in range(3000))}
    note = Atlas._page_text(_atlas(store), _run(long), turn, tmp_path)  # type: ignore[arg-type]
    saved = list(tmp_path.glob("page-*.md"))
    assert saved and "Line 2999" in saved[0].read_text(encoding="utf-8")
    assert "Line 0 " in note and "Line 2999" not in note and "all of it is in" in note
    assert len(note) < INLINE_CHARS + 2000
