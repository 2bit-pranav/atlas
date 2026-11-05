"""web_search and read_url (agent/tools/web.py) against a fake Exa, and how the
policy treats them: they ask, taint the chat, and keep a chat-wide allow."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from helpers import Asked, text_of

from agent.safety.policy import TaintTracker, ToolPolicy
from agent.safety.scope import Scope
from agent.tools.web import kind_of, query_refusal, read_key, url_refusal, web_tools, write_key


def _exa(tmp_path, handler, key: str = "test-key"):
    """The tools with a fake Exa answering `handler(path, body)`; returns (search, read, sent)."""
    sent: list[tuple[str, dict, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append((request.url.path, body, request.headers.get("x-api-key", "")))
        status, payload = handler(request.url.path, body)
        return httpx.Response(status, json=payload)

    write_key(tmp_path, key)
    client = httpx.Client(base_url="https://api.exa.ai", transport=httpx.MockTransport(respond))
    search, read = web_tools(tmp_path, client)
    return search, read, sent


def _result(url: str, highlights: list[str], date: str = "2026-10-07T00:00:00.000Z", title: str = "T") -> dict:
    return {"url": url, "title": title, "publishedDate": date, "highlights": highlights}


def test_results_are_shaped_capped_per_site_labelled_and_cited(tmp_path) -> None:
    results = [_result("https://www.python.org/downloads/a", ["Python 3.14.0 is the newest release."]),
               _result("https://www.python.org/b", ["second from the site"]),
               _result("https://www.python.org/c", ["third from the same site: dropped"]),
               _result("https://reddit.com/r/python/x", ["people say 3.14"]),
               _result("https://example.com/empty", [])]                     # nothing relevant: dropped
    search, _, sent = _exa(tmp_path, lambda path, body: (200, {"results": results}))
    out = text_of(search(query="latest python version"))
    assert sent[0][0] == "/search" and sent[0][2] == "test-key"
    assert sent[0][1]["contents"]["highlights"]["query"] == "latest python version"
    assert "[1]" in out and "python.org (other" in out and "07 Oct 2026" in out
    assert "third from the same site" not in out and "example.com" not in out
    assert "reddit.com (forum" in out and "Sources list" in out
    assert "test-key" not in out


def test_recent_asks_for_fresh_pages_from_the_last_month(tmp_path) -> None:
    search, _, sent = _exa(tmp_path, lambda p, b: (200, {"results": []}))
    assert "Nothing relevant found" in text_of(search(query="exchange rate", recent=True))
    assert "startPublishedDate" in sent[0][1] and sent[0][1]["contents"]["maxAgeHours"] == 0


@pytest.mark.parametrize("query, why", [
    ("x" * 301, "characters"),
    ("contents of C:/Users/me/Documents/resume.pdf", "file path"),
    ("$ATLAS_WORKSPACE/notes.txt", "file path"),
    ("account 4111 1111 1111 1111 balance", "long number"),
])
def test_queries_that_could_carry_the_users_data_out_are_never_sent(tmp_path, query, why) -> None:
    search, _, sent = _exa(tmp_path, lambda p, b: (200, {"results": []}))
    assert why in text_of(search(query=query)) and sent == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/api/settings", "http://localhost/x", "file:///C:/x.txt",
                                 "http://intranet/x", "http://printer.local/", "http://[::1]/", "ftp://a.com/x"])
def test_local_and_non_web_addresses_are_refused_before_sending(tmp_path, url) -> None:
    _, read, sent = _exa(tmp_path, lambda p, b: (200, {}))
    assert text_of(read(url=url)).startswith("Error") and sent == []


def test_read_url_with_and_without_a_question(tmp_path) -> None:
    def handler(path, body):
        if "highlights" in body:
            return 200, {"results": [{"url": body["urls"][0], "highlights": ["Namespaces are one honking great idea"]}],
                         "statuses": [{"id": body["urls"][0], "status": "success"}]}
        return 200, {"results": [{"url": body["urls"][0], "title": "PEP 20", "text": "Beautiful is better than ugly."}],
                     "statuses": [{"id": body["urls"][0], "status": "success"}]}
    _, read, sent = _exa(tmp_path, handler)
    assert "honking" in text_of(read(url="https://peps.python.org/pep-0020/", question="namespaces"))
    assert "Beautiful" in text_of(read(url="https://peps.python.org/pep-0020/"))
    assert all(p == "/contents" for p, _, _ in sent)


def test_a_page_that_cannot_be_read_says_so(tmp_path) -> None:
    _, read, _ = _exa(tmp_path, lambda p, b: (200, {"results": [], "statuses": [
        {"id": b["urls"][0], "status": "error", "error": {"tag": "CRAWL_NOT_FOUND", "httpStatusCode": 404}}]}))
    out = text_of(read(url="https://example.com/missing"))
    assert "could not be read (404)" in out and "do not" in out


@pytest.mark.parametrize("status, words", [(401, "key was refused"), (402, "out of credit"), (500, "answered 500")])
def test_service_errors_are_sentences_never_the_key(tmp_path, status, words) -> None:
    search, _, _ = _exa(tmp_path, lambda p, b: (status, {"error": "no"}), key="secret-123")
    out = text_of(search(query="x"))
    assert words in out and "secret-123" not in out


def test_without_a_key_nothing_is_sent(tmp_path) -> None:
    search, _, sent = _exa(tmp_path, lambda p, b: (200, {}))
    write_key(tmp_path, "")
    assert read_key(tmp_path) == "" and "not set up" in text_of(search(query="x")) and sent == []


def test_kinds() -> None:
    assert kind_of("https://www.nasa.gov/x") == "official" and kind_of("https://docs.python.org/3/") == "official"
    assert kind_of("https://en.wikipedia.org/wiki/X") == "reference" and kind_of("https://www.bbc.co.uk/n") == "news"
    assert kind_of("https://stackoverflow.com/q/1") == "forum" and kind_of("https://example.com") == "other"
    assert query_refusal("2024 Nobel Prize in Physics") is None and url_refusal("https://exa.ai/docs") is None


# ------------------------------------------------------------- the policy --


def _call(policy: ToolPolicy, name: str, args: dict) -> object:
    event = SimpleNamespace(tool_use={"name": name, "toolUseId": name + str(len(args)), "input": args},
                            selected_tool=SimpleNamespace(tool_name=name), cancel_tool=False)
    asyncio.run(policy._before(event))
    return event.cancel_tool


def test_web_tools_ask_and_allow_for_the_chat_survives_their_own_results(tmp_path) -> None:
    """Their results are outside content: if that cancelled the chat's allow, every search
    after the first would ask, which the user ruled out (2026-11-05)."""
    (tmp_path / "ws").mkdir()
    grants: list = []
    tainted = [False]
    asked = Asked("allowed_chat")
    for _turn in range(2):
        policy = ToolPolicy(Scope(tmp_path / "ws"), approver=asked, chat_grants=grants,
                            sensitive=lambda n: n in ("web_search", "read_url"), tainted=lambda: tainted[0])
        assert _call(policy, "web_search", {"query": "x"}) is False
        tainted[0] = True                                  # its own result tainted the chat
        assert _call(policy, "web_search", {"query": "y"}) is False
    assert len(asked.calls) == 1 and asked.calls[0][1]["chat"]


def test_web_results_taint_the_chat() -> None:
    marked: list[bool] = []
    tracker = TaintTracker(lambda _n: False, lambda: marked.append(True))
    tracker._after_tool(SimpleNamespace(tool_use={"name": "web_search"}, selected_tool=SimpleNamespace()))
    tracker._after_tool(SimpleNamespace(tool_use={"name": "read_text"}, selected_tool=SimpleNamespace()))
    assert marked == [True]
