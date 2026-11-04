"""Shared by the offline tests: an approver that records, an MCP tool, a
tool result's text, and a settings file for a throwaway Atlas."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class Asked:
    """An approver that answers with `answer` and records `(kind, detail)` for each question."""

    def __init__(self, answer: str = "allowed") -> None:
        self.answer, self.calls = answer, []

    async def __call__(self, kind: str, detail: dict) -> str:
        self.calls.append((kind, detail))
        return self.answer


def mcp_tool(name: str) -> Any:
    """An MCP tool called `name`, as the policy and the taint tracker see one."""
    from mcp import types as mcp_types
    from strands.tools.mcp.mcp_agent_tool import MCPAgentTool

    tool = mcp_types.Tool(name=name, description="", inputSchema={"type": "object"})
    return MCPAgentTool(tool, SimpleNamespace(), name_override=name)


def text_of(result: Any) -> str:
    """A tool's result as text: a plain string, or an error result's first block."""
    return result if isinstance(result, str) else result["content"][0]["text"]


def settings_file(tmp_path: Path) -> Path:
    """settings.example.json with its data and MCP config inside `tmp_path`."""
    settings = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    settings["paths"] = {"data_dir": str(tmp_path / "data")}
    settings["mcp"]["config"] = str(tmp_path / "mcp.json")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path
