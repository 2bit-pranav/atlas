"""Plan item 5: the floor, shell commands refused in every tier with no card
(agent/safety/rules.toml, agent/safety/rules.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.safety.rules import RuleError, Rules, floor

HOME = str(Path.home()).replace("\\", "/")


@pytest.mark.parametrize("command", [
    "format C: /q",
    "diskpart /s wipe.txt",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    "vssadmin delete shadows /all /quiet",
    "cipher /w:C:",
    "bcdedit /set {default} recoveryenabled no",
    "shutdown /s /t 0",
    "reg delete HKLM\\Software\\X /f",
    "rm -rf /",
    "rm -rf /c/",
    "rm -rf /c/*",
    "rm -rf ~",
    'rm -rf "$HOME"',
    f"rm -rf {HOME}",
    "rm -rf /c/Windows",
    'del /s /q "C:\\Program Files"',
    "ls && rm -rf /",
    'bash -c "rm -rf ~"',
    'powershell -Command "Format-Volume -DriveLetter D"',
])
def test_the_floor_refuses(command) -> None:
    assert floor(command), command


@pytest.mark.parametrize("command", [
    "ls -la",
    "rm -rf old",
    "rm -rf ./build",
    f"rm -rf {HOME}/Desktop/atlas-demo/out",
    "vssadmin list shadows",
    "cipher /c secret.txt",
    "reg query HKCU\\Software",
    "echo format C:",
    "grep shutdown notes.txt",
    "",
])
def test_ordinary_commands_pass_the_floor(command) -> None:
    assert floor(command) is None, command


def test_the_reason_names_the_rule() -> None:
    assert "disk" in floor("format C: /q")


def test_a_rule_whose_example_does_not_match_fails_to_load() -> None:
    bad = """
[[rule]]
name = "format a disk"
programs = ["format"]
refuse = ["diskpart /s x"]
"""
    with pytest.raises(RuleError, match="format a disk"):
        Rules.parse(bad)


def test_an_allow_example_that_matches_fails_to_load() -> None:
    bad = """
[[rule]]
name = "format a disk"
programs = ["format"]
refuse = ["format C:"]
allow = ["format D:"]
"""
    with pytest.raises(RuleError, match="format D:"):
        Rules.parse(bad)
