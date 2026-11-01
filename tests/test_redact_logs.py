"""Credentials never reach the UI in a skill's install output (agent/common/redact.py)."""

from __future__ import annotations

import subprocess

import pytest

from agent.common.redact import redact_text
from agent.integrations.skills import requirements

SECRET = "ghp_S3cretT0ken"


@pytest.mark.parametrize("text, kept", [
    (f"git+https://{SECRET}@github.com/o/r.git", "github.com/o/r.git"),
    (f"git+https://user:{SECRET}@github.com/o/r.git", "https://user:"),
    (f"pip install --index-url https://me:{SECRET}@pypi.example/simple x", "pypi.example/simple x"),
    (f"npm install --//registry.npmjs.org/:_authToken={SECRET} x", "x"),
    (f"tool --api-key {SECRET} --port 3000", "--port 3000"),
    (f"tool --token={SECRET}", "--token="),
    (f"https://api.example/v1?key=1&access_token={SECRET}", "key=1"),
])
def test_secrets_are_redacted(text, kept) -> None:
    shown = redact_text(text)
    assert SECRET not in shown and kept in shown, shown


@pytest.mark.parametrize("text", [
    "pip install rich==13.0 httpx>=0.27",
    "npm install -g @scope/pkg@1.2.3",
    "Successfully installed rich-13.0",
    "see https://github.com/o/r for details",
])
def test_ordinary_text_is_unchanged(text) -> None:
    assert redact_text(text) == text


def test_install_output_hides_a_token(tmp_path, monkeypatch) -> None:
    def fake_run(argv, **kwargs):
        # An index URL from the user's own pip config, echoed by pip.
        out = f"Looking in indexes: https://{SECRET}@pypi.example/simple\nCollecting {argv[-1]}\n"
        return subprocess.CompletedProcess(argv, 1, stdout=out, stderr="")

    monkeypatch.setattr(requirements.subprocess, "run", fake_run)
    monkeypatch.setattr(requirements, "with_status", lambda folder, reqs: [{**r, "installed": False} for r in reqs])
    out = requirements.install(tmp_path, [{"manager": "pip", "package": "rich", "scope": "env"}])
    assert "pypi.example/simple" in out["output"] and "Collecting rich" in out["output"]
    assert SECRET not in out["output"]


def test_a_requirement_with_a_url_is_never_listed(tmp_path) -> None:
    """Only plain package names are read, so a credential in a URL never reaches
    the Skills page or an install command line."""
    (tmp_path / "requirements.txt").write_text(f"rich\ngit+https://{SECRET}@github.com/o/private.git\n",
                                               encoding="utf-8")
    assert [r["package"] for r in requirements.detect(tmp_path)] == ["rich"]
