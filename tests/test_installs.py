"""B10: install commands are recognised by parsing, not one regex (agent/safety/installs.py)."""

from __future__ import annotations

import pytest

from agent.safety.installs import is_install


@pytest.mark.parametrize("command", [
    "pip install rich",
    "python -m pip install rich",
    "cd x && npm install y",
    "npx -y some-tool",
    "uvx ruff",
    "winget install Git.Git",
    # B10: all of these ran without asking.
    "   pip install rich",
    "echo start\npip install rich",
    "py -3 -m pip install rich",
    "py -3.14 -m pip install rich",
    r"C:\Python314\python.exe -m pip install rich",
    "/c/Python314/python.exe -m pip install rich",
    "pipx install black",
    "pipx run cowsay",
    "echo `pip install rich`",
    "echo $(npm i left-pad)",
    "X=1 pip install rich",
    "env PIP_INDEX_URL=x pip install rich",
    "sudo apt-get install curl",
    'bash -c "pip install rich"',
    'powershell -Command "Install-Module PSReadLine"',
    'cmd /c "npm install -g x"',
    "uv pip install rich",
    "uv tool install ruff",
    "uv add httpx",
    "npm exec cowsay",
    "pnpm dlx create-vite",
    "yarn global add x",
    "conda install numpy",
    "cargo install ripgrep",
    "pip3.14 install rich",
])
def test_installs_are_recognised(command: str) -> None:
    assert is_install(command), command


@pytest.mark.parametrize("command", [
    "pip list",
    "pip show rich",
    "python -m pip --version",
    "npm run build",
    "npm test",
    "echo pip install rich",                 # text, not a command
    "grep 'npm install' README.md",
    'python "$ATLAS_SKILLS/pdf/scripts/read_pdf.py" "notes.pdf"',
    "ls -la",
    "uv run pytest",
    "",
])
def test_ordinary_commands_are_not_installs(command: str) -> None:
    assert not is_install(command), command
