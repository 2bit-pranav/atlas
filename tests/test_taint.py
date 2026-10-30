"""B5: page taint belongs to the chat and covers every source of outside content.

Before: taint was a flag on one run. On the next message the page text was
still in the conversation but nothing asked any more, and `web_fetch` or a
web-reading MCP server never tainted at all.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp import types as mcp_types
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

from agent.integrations.mcp.pool import FOLDERS, McpManager, _Server
from agent.safety.policy import TaintTracker
from agent.store.chats import ChatStore
from server.state import Atlas

ROOT = Path(__file__).resolve().parents[1]


def _mcp(name: str) -> MCPAgentTool:
    tool = mcp_types.Tool(name=name, description="", inputSchema={"type": "object"})
    return MCPAgentTool(tool, SimpleNamespace(), name_override=name)


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


def test_web_fetch_and_untrusted_mcp_tools_taint() -> None:
    hits: list[str] = []
    tracker = TaintTracker(untrusted=lambda name: name == "ddg_fetch_content", on_taint=lambda: hits.append("x"))
    tracker._after_tool(_after("read"))                                   # a local file: no
    tracker._after_tool(_after("filesystem_read", _mcp("filesystem_read")))  # trusted MCP: no
    assert hits == []
    tracker._after_tool(_after("web_fetch"))
    tracker._after_tool(_after("ddg_fetch_content", _mcp("ddg_fetch_content")))
    assert len(hits) == 2


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
    settings = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    settings["paths"] = {"data_dir": str(tmp_path / "data")}
    settings["mcp"]["config"] = str(tmp_path / "mcp.json")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
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
