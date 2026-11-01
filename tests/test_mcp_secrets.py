"""B31: the UI never receives an MCP server's secrets, and editing a server in
the UI keeps them (agent/integrations/mcp/secrets.py)."""

from __future__ import annotations

import json

import pytest

from agent.integrations.mcp.pool import McpManager, _Server
from agent.integrations.mcp.secrets import REDACTED, redact, restore

CONFIG = {
    "command": "npx",
    "args": ["-y", "some-server", "--api-key", "sk-live-123", "--token=abc", "--port", "3000"],
    "env": {"GITHUB_TOKEN": "ghp_secret", "DEBUG": "1"},
    "headers": {"Authorization": "Bearer xyz"},
    "url": "https://mcp.example/sse?api_key=k-999&region=eu",
    "tool_filters": {"rejected": ["delete_repo"]},
}


def test_secrets_are_redacted() -> None:
    shown = json.dumps(redact(CONFIG))
    for secret in ("sk-live-123", "abc", "ghp_secret", "1\"", "Bearer xyz", "k-999"):
        assert secret not in shown, secret
    out = redact(CONFIG)
    assert out["args"][:3] == ["-y", "some-server", "--api-key"] and out["args"][3] == REDACTED
    assert out["args"][4] == f"--token={REDACTED}"
    assert out["args"][5:] == ["--port", "3000"]                      # not a secret
    assert out["env"] == {"GITHUB_TOKEN": REDACTED, "DEBUG": REDACTED}
    assert "region=eu" in out["url"]
    assert out["tool_filters"] == CONFIG["tool_filters"]
    assert CONFIG["env"]["GITHUB_TOKEN"] == "ghp_secret"              # the original is untouched


def test_an_unchanged_edit_keeps_the_secrets() -> None:
    edited = redact(CONFIG)
    edited["args"][-1] = "4000"                                       # the user changes the port only
    saved = restore(edited, CONFIG)
    assert saved["env"]["GITHUB_TOKEN"] == "ghp_secret"
    assert saved["args"][3] == "sk-live-123" and saved["args"][4] == "--token=abc"
    assert saved["headers"]["Authorization"] == "Bearer xyz"
    assert saved["url"] == CONFIG["url"]
    assert saved["args"][-1] == "4000"


def test_a_new_value_replaces_the_secret() -> None:
    edited = redact(CONFIG)
    edited["env"]["GITHUB_TOKEN"] = "ghp_new"
    assert restore(edited, CONFIG)["env"]["GITHUB_TOKEN"] == "ghp_new"


def test_a_placeholder_with_nothing_behind_it_is_refused() -> None:
    edited = redact(CONFIG)
    edited["env"]["NEW_KEY"] = REDACTED
    with pytest.raises(ValueError):
        restore(edited, CONFIG)


def test_describe_and_upsert_round_trip(tmp_path) -> None:
    manager = McpManager.__new__(McpManager)
    manager._lock = __import__("threading").RLock()
    manager._servers = {"gh": _Server("gh", CONFIG)}
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"gh": CONFIG}}), encoding="utf-8")
    manager.config_path = lambda: path
    manager._connect = lambda name, config: _Server(name, config)       # no process in a test
    shown = manager._servers["gh"].describe()["config"]
    assert "ghp_secret" not in json.dumps(shown)
    manager.upsert("gh", shown)
    stored = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["gh"]
    assert stored["env"]["GITHUB_TOKEN"] == "ghp_secret"
