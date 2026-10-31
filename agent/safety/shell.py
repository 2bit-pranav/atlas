"""What a shell command does, by parsing it (tree-sitter-bash), not matching it.

Each simple command (inside pipelines, lists, `$(...)`, backticks, loops,
`if`, functions, and `bash -c "..."`) is placed in one class:

    read     looks only: ls, cat, grep, a skill's reader script
    write    creates or changes files: `>`, cp, mv, mkdir, touch, tee, sed -i
    delete   removes files: rm, rmdir, del, find -delete
    install  installs or fetches and runs packages (installs.py has the rules)
    other    anything else: python -c, curl, git, xargs, an unknown program

A command's class is its worst part's. Writes and deletes name the paths they
target, as written (variables unexpanded), for the tiers to place. A command
that does not parse is `other`. The cost of an unknown command is an
approval card, never a command let through: a program not on the read list
is `other`, so reading is the one class that must be proven.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import PureWindowsPath
from typing import Any

from agent.safety.installs import installs

KINDS = ("read", "write", "delete", "install", "other")   # in order of severity

#: Programs that only look. Anything not here is `other` unless placed below.
_READ = {
    "ls", "dir", "cat", "head", "tail", "less", "more", "wc", "grep", "egrep", "fgrep", "rg",
    "stat", "file", "echo", "printf", "pwd", "cd", "which", "where", "type", "date", "whoami",
    "hostname", "uniq", "cut", "tr", "diff", "cmp", "du", "df", "tree", "basename", "dirname",
    "realpath", "readlink", "test", "[", "[[", "true", "false", "sleep", "jq", "nl", "column",
    "md5sum", "sha1sum", "sha256sum", "cygpath", "uname", "id", "ps", "seq", "expr", "comm",
}
_WRITE = {"cp", "mv", "mkdir", "touch", "tee", "ln", "install", "copy", "move", "md", "xcopy", "robocopy"}
_DELETE = {"rm", "rmdir", "del", "erase", "rd", "unlink", "shred"}
_SHELLS = {"bash", "sh", "zsh", "dash"}
#: Shells whose language is not bash: what they run is `other` (or `install`).
_FOREIGN = {"cmd", "powershell", "pwsh"}
_PREFIXES = {"sudo", "env", "command", "exec", "nohup", "time", "nice", "builtin"}
#: Skill scripts that only read (`python "$ATLAS_SKILLS/pdf/scripts/read_pdf.py" ...`).
_READER = re.compile(r"(^|[/\\])(read|list|inspect|search|info|show)_[\w-]*\.py$", re.I)
_PYTHON = re.compile(r"^(?:python|py|pythonw)(?:\d+(?:\.\d+)*)?$")
_NULL = {"/dev/null", "nul", "/dev/stdout", "/dev/stderr"}
#: A sed script that only prints lines: `1,20p`, `$p`, `/x/p`, `=`.
_SED_PRINT = re.compile(r"(?:[0-9$,~+]*|/[^/]*/(?:,/[^/]*/)?)?[p=]?|[0-9]+q")


@dataclass(frozen=True)
class Effect:
    kind: str
    program: str
    paths: tuple[str, ...] = ()


@dataclass
class Classification:
    effects: list[Effect] = field(default_factory=list)
    parsed: bool = True

    @property
    def kind(self) -> str:
        worst = max((KINDS.index(e.kind) for e in self.effects), default=0)
        return "other" if not self.parsed else KINDS[worst]

    @property
    def installs(self) -> bool:
        return any(e.kind == "install" for e in self.effects)

    def paths(self, kind: str) -> list[str]:
        return [p for e in self.effects if e.kind == kind for p in e.paths]


def classify(command: str) -> Classification:
    return _classify(command or "", 0)


def is_install(command: str) -> bool:
    """Whether `command` installs anything (asked before it runs)."""
    return classify(command).installs


# ------------------------------------------------------------------ walk --

@cache
def _parser() -> Any:
    import tree_sitter_bash
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_bash.language()))


def _classify(command: str, depth: int) -> Classification:
    out = Classification()
    if depth > 4:
        out.parsed = False
        return out
    tree = _parser().parse(command.encode("utf-8"))
    out.parsed = not tree.root_node.has_error
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "command":
            out.effects += _command(node, depth)
        elif node.type == "file_redirect":
            out.effects += _redirect(node)
        stack.extend(reversed(node.named_children))
    return out


def _text(node: Any) -> str:
    """An argument's value as the shell would see it, quotes removed."""
    if node.type == "command_name" and node.named_child_count == 1:
        return _text(node.named_children[0])     # r''m is rm
    raw = node.text.decode("utf-8", "replace")
    if node.type == "raw_string":
        return raw[1:-1]
    if node.type == "string":
        return raw[1:-1] if raw[:1] == raw[-1:] == '"' else raw
    if node.type == "concatenation":
        return "".join(_text(c) for c in node.children)
    return raw


def _redirect(node: Any) -> list[Effect]:
    operator = next((c.text.decode() for c in node.children if not c.is_named), "")
    target = node.child_by_field_name("destination")
    if target is None or ">" not in operator or target.type == "number" or operator.startswith(">&"):
        return []                          # `<` reads; `2>&1` duplicates a descriptor
    path = _text(target)
    if path.lower() in _NULL:
        return []
    return [Effect("write", operator, (path,))]


def _command(node: Any, depth: int) -> list[Effect]:
    name = node.child_by_field_name("name")
    if name is None:
        return []                          # only assignments: `X=1`
    words = [_text(name), *(_text(c) for c in node.children_by_field_name("argument"))]
    while words and (words[0].lower() in _PREFIXES or re.match(r"^[A-Za-z_]\w*=", words[0])):
        words = words[1:]
    if not words:
        return []
    program = _program(words[0])
    args = words[1:]
    if installs(words):
        return [Effect("install", program)]
    if program in _SHELLS or program in _FOREIGN:
        flag = next((i for i, a in enumerate(args) if a.lower() in ("-c", "/c", "/k", "-command", "-c:")), None)
        if flag is None or flag + 1 >= len(args):
            return [Effect("other", program)]
        inner = _classify(" ".join(args[flag + 1:]), depth + 1)
        if program in _FOREIGN:            # not bash: only its installs are trusted
            return [Effect("install" if inner.installs else "other", program)]
        return inner.effects + ([] if inner.parsed else [Effect("other", program)]) or [Effect("read", program)]
    if program in _DELETE:
        return [Effect("delete", program, tuple(_operands(args)))]
    if program == "find":
        if "-delete" in args:
            return [Effect("delete", program, tuple(_operands(args[:1])))]
        if any(a in ("-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls") for a in args):
            return [Effect("other", program)]
        return [Effect("read", program)]
    if program == "sed":
        if any(a == "-i" or a.startswith(("-i", "--in-place")) for a in args):
            return [Effect("write", program, tuple(_operands(args)[1:]))]
        # Only printing is read: a sed script can also write (w) and run commands (e).
        script = (_operands(args) or [""])[0]
        return [Effect("read" if _SED_PRINT.fullmatch(script) else "other", program)]
    if program == "uniq" and len(_operands(args)) > 1:
        return [Effect("write", program, (_operands(args)[1],))]
    if (program == "date" and any(a.startswith(("-s", "--set")) for a in args))             or (program == "hostname" and _operands(args)) or (program == "file" and "-C" in args):
        return [Effect("other", program)]       # set the clock, rename the machine, write a magic file
    if program == "sort":
        if any(a == "-o" or a.startswith(("-o", "--output")) for a in args):
            return [Effect("other", program)]
        return [Effect("read", program)]
    if program in _WRITE:
        operands = _operands(args)
        if program in ("cp", "copy", "xcopy", "robocopy", "install", "ln"):
            operands = operands[-1:]       # the destination; sources are only read
        return [Effect("write", program, tuple(operands))]
    if _PYTHON.match(program) and args and not args[0].startswith("-") and _READER.search(args[0]):
        return [Effect("read", program)]
    if program in _READ:
        return [Effect("read", program)]
    return [Effect("other", program)]


def _program(word: str) -> str:
    name = PureWindowsPath(word.replace("/", "\\")).name.lower()
    return re.sub(r"\.(exe|cmd|bat|ps1)$", "", name)


def _operands(args: list[str]) -> list[str]:
    """The arguments that are not options (`--` ends the options)."""
    out, options = [], True
    for a in args:
        if options and a == "--":
            options = False
        elif options and a.startswith("-") and a != "-":
            continue
        elif options and re.match(r"^/[a-zA-Z]$", a):   # cmd's /s /q
            continue
        else:
            out.append(a)
    return out


__all__ = ["KINDS", "Classification", "Effect", "classify", "is_install"]
