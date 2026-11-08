"""Shell commands are parsed (tree-sitter-bash) and each simple
command is placed as read, write, delete, install or other (agent/safety/shell.py).

The tiers decide what each class does; this only has to be right about which
class, and never place something dangerous as read.
"""

from __future__ import annotations

import pytest

from agent.safety.shell import classify


@pytest.mark.parametrize("command", [
    "ls -la",
    "cat notes.txt | grep total | wc -l",
    "head -n 5 data.csv && tail -n 5 data.csv",
    'echo "rm -rf / is dangerous"',              # text, not a delete
    "cd out && pwd",
    "find . -name '*.pdf'",
    "grep -r 'npm install' .",
    'python "$ATLAS_SKILLS/pdf/scripts/read_pdf.py" "notes.pdf"',
    "sed -n 1,20p file.txt",
    "diff a.txt b.txt > /dev/null",
    "",
])
def test_read_only(command) -> None:
    assert classify(command).kind == "read", classify(command)


@pytest.mark.parametrize("command, path", [
    ("echo hi > note.txt", "note.txt"),
    ("cat a >> /c/Users/me/log.txt", "/c/Users/me/log.txt"),
    ("cp a.txt /c/Users/me/Desktop/", "/c/Users/me/Desktop/"),
    ("mv draft.docx final.docx", "final.docx"),
    ("mkdir -p out/reports", "out/reports"),
    ("touch x.md", "x.md"),
    ("ls | tee listing.txt", "listing.txt"),
    ("sed -i 's/a/b/' config.ini", "config.ini"),
])
def test_writes_name_their_targets(command, path) -> None:
    result = classify(command)
    assert result.kind == "write", result
    assert path in result.paths("write")


@pytest.mark.parametrize("command", [
    "rm -rf old",
    "ls && rm notes.txt",
    "echo $(rm x)",
    "find . -name '*.tmp' -delete",
    "rmdir empty",
    "del /s /q C:\\Users\\me\\x",
])
def test_deletes(command) -> None:
    assert classify(command).kind == "delete", classify(command)


@pytest.mark.parametrize("command", [
    'python -c "import os; os.remove(\'x\')"',
    "curl https://example.com -o x.sh",
    "git push",
    "find . -exec rm {} \\;",
    "ls | xargs rm",
    "eval \"$CMD\"",
    "some-unknown-tool --flag",
    "node script.js",
    "for f in *.txt; do rm $f; done",         # the rm is still found: delete, or worse
    "if [ -f x ]; then python x.py; fi",
])
def test_anything_else_is_other_or_worse(command) -> None:
    assert classify(command).kind in ("delete", "install", "other"), classify(command)
    assert classify(command).kind != "read"


def test_install_is_its_own_class() -> None:
    assert classify("pip install rich").kind == "install"
    assert classify("ls && npm i left-pad").kind == "install"


def test_the_worst_part_decides() -> None:
    assert classify("ls; echo hi > x.txt; rm y").kind == "delete"


def test_a_command_that_does_not_parse_is_other() -> None:
    assert classify("echo 'unterminated").kind == "other"


def test_bash_c_is_looked_inside() -> None:
    assert classify('bash -c "rm -rf x"').kind == "delete"
    assert classify("sh -c 'ls -la'").kind == "read"


@pytest.mark.parametrize("command", [
    "sed -n 'w stolen.txt' notes.txt",          # sed's w writes a file
    "sed 'e rm -rf x' notes.txt",               # GNU sed's e runs a command
    "date -s '2020-01-01'",
    "hostname evil",
    "file -C -m magic",
])
def test_readers_that_can_change_things_are_not_read(command) -> None:
    assert classify(command).kind != "read", classify(command)


def test_uniq_writes_its_second_operand() -> None:
    result = classify("uniq in.txt out.txt")
    assert result.kind == "write" and result.paths("write") == ["out.txt"]


@pytest.mark.parametrize("command", ["\\rm x", "r''m x", "/bin/rm x", "f() { rm x; }; f"])
def test_a_disguised_rm_is_still_found(command) -> None:
    assert "delete" in [e.kind for e in classify(command).effects], classify(command)
