"""A video's key moments (agent/extension/moments.py, POST /api/chats/{id}/moments): chapters
read without a model, else one model call whose times must be the transcript's own; saved
as a finished turn with no run."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from helpers import settings_file

from agent.extension import moments
from server.app import create_app

CHAPTERED = """# But what is a neural network?

Channel: 3Blue1Brown · Length: 18:40

## Description
Help fund future projects: patreon
0:00 Introduction example
3:20 Series preview
8:40 What are neurons?
12:15 [Click](http://evil.example) *here*

## Transcript
[0:04] This is a 3, sloppily written
[3:20] two hidden layers"""

PLAIN = """# A talk

## Description
No chapters here. Mentioned at 4:00 in passing.

## Transcript
[0:04] Hello and welcome
[1:30] The first idea is caching
[5:10] Now the second idea, batching
[9:00] To sum up"""


def test_chapters_follow_youtubes_rule() -> None:
    assert [t for t, _ in moments.chapters(moments.section(CHAPTERED, "Description"))] == ["0:00", "3:20", "8:40", "12:15"]
    assert moments.chapters("1:00 a\n2:00 b\n3:00 c") == []            # must start at 0:00
    assert moments.chapters("0:00 a\n2:00 b") == []                     # at least three
    assert moments.chapters("0:00 a\n5:00 b\n2:00 c") == []             # in order


def test_the_models_moments_keep_only_real_times() -> None:
    answer = {"moments": [{"time": "5:10", "label": "Batching"}, {"time": "7:77", "label": "made up"},
                          {"time": "1:30", "label": "Caching\nfirst"}, {"time": "1:30", "label": "again"},
                          {"time": "0:04", "label": "  "}]}
    assert moments.checked(answer, ["0:04", "1:30", "5:10", "9:00"]) == [("1:30", "Caching first"), ("5:10", "Batching")]
    assert moments.checked("nonsense", ["0:04"]) == []


def test_a_long_transcript_is_merged_to_fit() -> None:
    rows = [(f"{i}:00", "word " * 40) for i in range(60)]
    fitted = moments._fit(rows, limit=3000)
    assert sum(len(t) + len(x) + 4 for t, x in fitted) <= 3000
    assert fitted[0][0] == "0:00" and len(fitted) < len(rows)


def test_page_text_cannot_add_links_or_times() -> None:
    text = moments.answer_text("Video", {"source": "chapters", "moments": [("12:15", "[Click](http://evil.example) *here* [1:00]")]})
    assert "](" not in text and "*here*" not in text and "[1:00]" not in text
    assert "- [12:15] Click http://evil.example here 1:00" in text


@pytest.fixture
def app_client(tmp_path):
    app = create_app(settings_file(tmp_path))
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    token = (tmp_path / "data" / "pairing-token").read_text(encoding="utf-8").strip()
    c.headers.update({"Origin": "chrome-extension://abc", "Authorization": f"Bearer {token}"})
    c.chat = c.post("/api/chats", json={"title": ""}).json()["id"]
    yield c
    app.state.atlas.close()


def _page(content: str) -> dict:
    return {"page": {"url": "https://www.youtube.com/watch?v=x", "title": "x - YouTube", "kind": "youtube", "content": content}}


def test_chapters_become_a_finished_turn_without_the_model(app_client, monkeypatch) -> None:
    monkeypatch.setattr(moments.httpx, "post", lambda *a, **k: pytest.fail("no model call for chapters"))
    r = app_client.post(f"/api/chats/{app_client.chat}/moments", json=_page(CHAPTERED))
    assert r.status_code == 200, r.text
    chat = r.json()["chat"]
    [turn] = chat["turns"]
    assert turn["status"] == "completed" and turn["user_text"] == "Key moments of this video"
    text = turn["render"][0]["text"]
    assert text.startswith("Found 4 key moments in *But what is a neural network?*, from its chapters.")
    assert "- [8:40] What are neurons?" in text
    assert chat["title"] == "Key moments: But what is a neural network?"
    assert chat["tainted"]
    # The next message goes on from it, as from any answer.
    again = app_client.post(f"/api/chats/{app_client.chat}/moments", json=_page(CHAPTERED)).json()["chat"]
    assert [t["parent_id"] for t in again["turns"]] == [None, turn["id"]]


def test_without_chapters_the_model_picks_from_the_transcript(app_client, monkeypatch) -> None:
    seen = {}

    class Reply:
        def raise_for_status(self) -> None: ...
        def json(self):
            content = {"moments": [{"time": "1:30", "label": "Caching"}, {"time": "4:00", "label": "not a passage"}]}
            return {"choices": [{"message": {"content": json.dumps(content)}}]}

    def post(url, json, headers, timeout):
        seen["schema"] = json["response_format"]["json_schema"]["schema"]
        return Reply()

    monkeypatch.setattr(moments.httpx, "post", post)
    r = app_client.post(f"/api/chats/{app_client.chat}/moments", json=_page(PLAIN))
    assert r.status_code == 200, r.text
    assert seen["schema"]["properties"]["moments"]["items"]["properties"]["time"]["enum"] == ["0:04", "1:30", "5:10", "9:00"]
    text = r.json()["chat"]["turns"][0]["render"][0]["text"]
    assert text == "Found 1 key moment in *A talk*, from its transcript.\n\n- [1:30] Caching"


def test_only_a_video_and_only_when_something_is_found(app_client) -> None:
    url = f"/api/chats/{app_client.chat}/moments"
    page = _page(CHAPTERED)
    page["page"]["kind"] = "article"
    assert app_client.post(url, json=page).status_code == 422
    assert app_client.post(url, json=_page("# Silent\n\n## Transcript\n(none)")).status_code == 422
    assert app_client.get(f"/api/chats/{app_client.chat}").json()["turns"] == []
