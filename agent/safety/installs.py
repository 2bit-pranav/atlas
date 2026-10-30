"""What counts as an install command (asked before it runs).

Parsed, not matched: one regex over the whole string missed a leading newline,
`py -3 -m pip`, a full path to `python.exe`, `X=1 pip install`, `pipx`, an
install inside backticks or `$(...)`, and `bash -c "..."`. Each of those ran
without asking. Here the command is split into simple commands (on `;`, `&&`,
`||`, `|`, newlines, and inside `$(...)`, backticks and `-c` strings), and
each one's program is named by its base name. An extra card is the failure
mode to prefer: a missed install runs code from the internet unasked.
"""

from __future__ import annotations

import re
import shlex
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
_SHELLS = {"bash", "sh", "zsh", "cmd", "powershell", "pwsh"}
_PREFIXES = {"sudo", "env", "command", "exec", "nohup", "time", "start", "call", "&"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEPARATORS = re.compile(r"\n|;|&&|\|\||\|")


def is_install(command: str) -> bool:
    return any(_installs(words) for words in _commands(command or ""))


def _commands(text: str, depth: int = 0) -> list[list[str]]:
    """Every simple command in `text`, as words, including nested ones."""
    if depth > 4:
        return []
    out: list[list[str]] = []
    nested = re.findall(r"\$\(([^()]*)\)", text) + re.findall(r"`([^`]*)`", text)
    for inner in nested:
        out += _commands(inner, depth + 1)
    for part in _SEPARATORS.split(text):
        words = _words(part)
        if not words:
            continue
        out.append(words)
        program = _program(_strip_prefixes(words)[:1])
        if program in _SHELLS:
            for i, w in enumerate(words):
                if w.lower() in ("-c", "/c", "/k", "-command", "-c:"):
                    out += _commands(" ".join(words[i + 1:]), depth + 1)
                    break
    return out


def _words(part: str) -> list[str]:
    # A backslash here is a Windows path separator (C:\Python314\python.exe), not
    # an escape; POSIX splitting would drop it and the program's name with it.
    part = part.replace("\\", "/")
    try:
        return shlex.split(part, posix=True)
    except ValueError:
        return part.split()


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


def _installs(words: list[str]) -> bool:
    words = _strip_prefixes(words)
    program = _program(words)
    args = [w.lower() for w in words[1:]]
    if _PYTHON.match(program):
        # python [-flags] -m pip|pipx|uv ...: the module is the program.
        if "-m" in args and args.index("-m") + 1 < len(args):
            module = args[args.index("-m") + 1]
            return _installs([module, *args[args.index("-m") + 2:]])
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


__all__ = ["is_install"]
