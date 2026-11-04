"""B5: page taint belongs to the chat and covers every source of outside content.

Before: taint was a flag on one run. On the next message the page text was
still in the conversation but nothing asked any more, and a
web-reading MCP server never tainted at all.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from helpers import mcp_tool, settings_file

from agent.integrations.mcp.pool import FOLDERS, McpManager, _Server
from agent.safety.policy import TaintTracker
from agent.store.chats import ChatStore
from server.state import Atlas


def _after(name: str, tool=None) -> SimpleNamespace:
    return SimpleNamespace(tool_use={"name": name, "toolUseId": "t1", "input": {}}, selected_tool=tool,
                           result={"status": "success", "content": [{"text": "outside text"}]})


def test_taint_is_stored_on_the_chat(tmp_path) -> None:
    store = ChatStore(tmp_path / "atlas.db")
    try:
        chat = store.create_chat()["id"]
        other = store.create_chat()["id"]
        assert not store.is_tainted(chat)
        store.mark_tainted(chat)
        assert store.is_tainted(chat) and not store.is_tainted(other)
    finally:
        store.close()


def test_untrusted_mcp_tools_taint() -> None:
    hits: list[str] = []
    tracker = TaintTracker(untrusted=lambda name: name == "ddg_fetch_content", on_taint=lambda: hits.append("x"))
    tracker._after_tool(_after("read_text"))                                 # a local file: no
    tracker._after_tool(_after("filesystem_read", mcp_tool("filesystem_read")))  # trusted MCP: no
    assert hits == []
    tracker._after_tool(_after("ddg_fetch_content", mcp_tool("ddg_fetch_content")))
    assert len(hits) == 1


def test_which_mcp_servers_are_trusted() -> None:
    manager = McpManager.__new__(McpManager)
    manager._lock = __import__("threading").RLock()
    manager._servers = {}

    def server(name: str, config: dict) -> None:
        s = _Server(name, config)
        s.tools = [SimpleNamespace(tool_name=f"{name}_tool")]
        manager._servers[name] = s

    server("filesystem", {"command": "npx", "args": ["-y", "server-filesystem", FOLDERS]})  # Atlas's folders only
    server("ddg", {"command": "uvx", "args": ["duckduckgo-mcp-server"]})
    server("mine", {"command": "x", "atlas": {"trusted": True}})
    assert not manager.is_untrusted("filesystem_tool")
    assert manager.is_untrusted("ddg_tool")
    assert not manager.is_untrusted("mine_tool")
    assert not manager.is_untrusted("not_an_mcp_tool")


@pytest.fixture
def atlas(tmp_path):
    path = settings_file(tmp_path)
    state = Atlas(path)
    yield state
    state.close()


def test_a_new_run_in_a_tainted_chat_starts_tainted(atlas) -> None:
    chat = atlas.store.create_chat()["id"]
    atlas.store.mark_tainted(chat)
    turn = atlas.store.insert_turn(chat, "next message", parent_turn_id=None, before_snap=None)

    async def scenario() -> bool:
        run = atlas.launch(turn, thinking=False)
        tainted = run.tainted
        run.task.cancel()
        try:
            await run.task
        except asyncio.CancelledError:
            pass
        return tainted

    assert asyncio.run(scenario()) is True


def test_tainting_a_run_marks_its_chat(atlas) -> None:
    chat = atlas.store.create_chat()["id"]
    run = atlas.runs.start(chat, "t1")
    atlas.taint(run)
    assert run.tainted and atlas.store.is_tainted(chat)


def test_tainting_tells_the_ui_once(atlas) -> None:
    """The UI shows that the chat has read outside content, from the moment it does."""
    chat = atlas.store.create_chat()["id"]
    run = atlas.runs.start(chat, "t1")
    atlas.taint(run)
    atlas.taint(run)
    assert [e["type"] for e in run.events].count("tainted") == 1
    assert atlas.view(chat)["tainted"]
