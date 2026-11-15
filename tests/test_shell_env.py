"""What a shell command inherits from the backend (agent/platform/windows_shell.py)."""

from __future__ import annotations

import asyncio

from agent.platform import windows_shell
from agent.platform.windows_shell import WindowsLocalEnvironment, inherited_env


def test_secrets_are_not_inherited(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LLAMA_KEY", "llama-secret")
    monkeypatch.setenv("ATLAS_RESTART_REQUEST", "C:/x/restart.request")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.setenv("MY_API_KEY", "api-secret")
    monkeypatch.setenv("ORDINARY_SETTING", "kept")
    env = inherited_env()
    assert env.get("ORDINARY_SETTING") == "kept" and "PATH" in {k.upper() for k in env}
    assert not {"ATLAS_LLAMA_KEY", "ATLAS_RESTART_REQUEST", "GITHUB_TOKEN", "MY_API_KEY"} & set(env)
    # The variables a command is meant to have are set after the filter.
    assert windows_shell._venv_first({"ATLAS_WORKSPACE": "/c/ws"})["ATLAS_WORKSPACE"] == "/c/ws"


def test_a_command_that_runs_cannot_print_the_llama_key(tmp_path, monkeypatch) -> None:
    """Every command inherited the backend's whole environment (2026-11-12)."""
    monkeypatch.setenv("ATLAS_LLAMA_KEY", "llama-secret")
    monkeypatch.setenv("ORDINARY_SETTING", "kept")
    shell = WindowsLocalEnvironment(cwd=tmp_path, skills=tmp_path / "skills", folders=[])

    async def run(command: str) -> str:
        out = ""
        async for chunk in shell.execute_streaming(command, timeout=30):
            out += str(getattr(chunk, "stdout", "") or "")
        return out

    printed = asyncio.run(run('echo "key=[$ATLAS_LLAMA_KEY] kept=[$ORDINARY_SETTING] skills=[$ATLAS_SKILLS]"; env'))
    assert "llama-secret" not in printed
    assert "key=[]" in printed and "kept=[kept]" in printed and "skills=[]" not in printed
