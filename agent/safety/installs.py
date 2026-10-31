"""What counts as an install command (asked before it runs): the rules.

`shell.py` parses a command and calls `installs(words)` on each simple command
it finds (in pipelines, lists, `$(...)`, backticks, loops and `-c` strings).
A program is named by its base name, so a full path to `python.exe` or
`pip3.14` counts. An extra card is the failure mode to prefer: a missed
install runs code from the internet unasked.
"""

from __future__ import annotations

import re
from pathlib import PureWindowsPath

#: program -> the subcommands that install (or fetch and run) packages; `None`: any use.
_INSTALLERS: dict[str, set[str] | None] = {
    "pip": {"install", "download"},
    "pipx": {"install", "run", "inject", "upgrade", "reinstall"},
    "uv": {"add"},
    "uvx": None,
    "npm": {"install", "i", "add", "ci", "exec", "x", "update", "upgrade"},
    "npx": None,
    "pnpm": {"add", "install", "i", "dlx", "update"},
    "pnpx": None,
    "yarn": {"add", "dlx", "install"},
    "bun": {"add", "install", "i", "x"},
    "bunx": None,
    "conda": {"install", "create"},
    "mamba": {"install", "create"},
    "micromamba": {"install", "create"},
    "winget": {"install", "upgrade"},
    "choco": {"install", "upgrade"},
    "scoop": {"install", "update"},
    "apt": {"install"},
    "apt-get": {"install"},
    "brew": {"install", "upgrade"},
    "dnf": {"install"},
    "yum": {"install"},
    "cargo": {"install"},
    "go": {"install", "get"},
    "gem": {"install"},
    "install-module": None,
    "install-package": None,
    "install-script": None,
}
#: Two-word subcommands: `uv pip install`, `uv tool install`, `yarn global add`.
_PAIRS = {("uv", "pip"): {"install"}, ("uv", "tool"): {"install", "run"}, ("yarn", "global"): {"add"}}
_PYTHON = re.compile(r"^(?:python|py|pythonw)(?:\d+(?:\.\d+)*)?$")
_PREFIXES = {"sudo", "env", "command", "exec", "nohup", "time", "start", "call", "&"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _strip_prefixes(words: list[str]) -> list[str]:
    i = 0
    while i < len(words) and (words[i].lower() in _PREFIXES or _ASSIGN.match(words[i])):
        i += 1
    return words[i:]


def _program(words: list[str]) -> str:
    if not words:
        return ""
    name = PureWindowsPath(words[0].replace("/", "\\")).name.lower()
    return re.sub(r"\.(exe|cmd|bat|ps1)$", "", name)


def installs(words: list[str]) -> bool:
    """Whether one simple command, as words, installs."""
    words = _strip_prefixes(words)
    program = _program(words)
    args = [w.lower() for w in words[1:]]
    if _PYTHON.match(program):
        # python [-flags] -m pip|pipx|uv ...: the module is the program.
        if "-m" in args and args.index("-m") + 1 < len(args):
            module = args[args.index("-m") + 1]
            return installs([module, *args[args.index("-m") + 2:]])
        return False
    base = re.sub(r"\d+(\.\d+)*$", "", program)  # pip3.14 -> pip
    if base not in _INSTALLERS:
        return False
    rule = _INSTALLERS[base]
    if rule is None:
        return True
    subcommands = [a for a in args if not a.startswith("-")]
    if not subcommands:
        return False
    pair = _PAIRS.get((base, subcommands[0]))
    if pair is not None:
        return len(subcommands) > 1 and subcommands[1] in pair
    return subcommands[0] in rule


__all__ = ["installs"]
