"""The floor: shell commands refused in every tier, with no card (rules.toml).

Data, not code, so the list can be read and reviewed in one place; each rule
carries example commands that are checked when the file loads, so a rule that
stopped matching (a typo, a parser change) fails loudly instead of silently
letting its commands through. Matching runs on `shell.classify`'s parse, so a
rule sees commands wherever they are nested.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from agent.safety.shell import classify

RULES_FILE = Path(__file__).with_name("rules.toml")


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    name: str
    programs: frozenset[str]
    args: tuple[str, ...]
    text: tuple[str, ...]

    def matches(self, command: str) -> bool:
        lowered = command.lower()
        if any(t in lowered for t in self.text):
            return True
        for effect in classify(command).effects:
            if effect.program in self.programs and (
                    not self.args or any(a.lower().startswith(self.args) for a in effect.args)):
                return True
        return False


@dataclass(frozen=True)
class Rules:
    rules: tuple[Rule, ...]
    delete_name: str
    delete_targets: frozenset[str]

    @classmethod
    def parse(cls, source: str) -> Rules:
        data = tomllib.loads(source)
        rules = tuple(Rule(r["name"], frozenset(p.lower() for p in r.get("programs", [])),
                           tuple(a.lower() for a in r.get("args", [])),
                           tuple(t.lower() for t in r.get("text", [])))
                      for r in data.get("rule", []))
        delete = data.get("delete", {})
        out = cls(rules, delete.get("name", "delete a protected folder"),
                  frozenset(_normal(t) for t in delete.get("targets", [])))
        out._check(data)
        return out

    def refuses(self, command: str) -> str | None:
        """The name of the rule `command` breaks, or None."""
        for rule in self.rules:
            if rule.matches(command):
                return rule.name
        if any(_normal(p) in self.delete_targets for p in classify(command).paths("delete")):
            return self.delete_name
        return None

    def _check(self, data: dict) -> None:
        sections = [(r["name"], r) for r in data.get("rule", [])]
        if "delete" in data:
            sections.append((self.delete_name, data["delete"]))
        for name, section in sections:
            for example in section.get("refuse", []):
                if self.refuses(example) != name:
                    raise RuleError(f"rules.toml: {name!r} does not refuse its example {example!r}")
            for example in section.get("allow", []):
                if (broken := self.refuses(example)) is not None:
                    raise RuleError(f"rules.toml: {example!r} is listed as allowed by {name!r}, "
                                    f"but {broken!r} refuses it")


def _normal(path: str) -> str:
    """One spelling per place: forward slashes, no trailing `/` or `/*`, case
    ignored, `C:/x` written `/c/x`, the home folder as written in the rules."""
    p = path.strip().strip("\"'").replace("\\", "/")
    home = str(Path.home()).replace("\\", "/")
    p = p.replace("{home}", home)
    while p.endswith(("/*", "/")) and len(p) > 1:
        p = p[:-2] if p.endswith("/*") else p[:-1]
    if m := re.match(r"^([A-Za-z]):(/.*)?$", p):
        p = f"/{m[1]}{m[2] or ''}"
    if p == "":
        p = "/"
    return p.lower()


@cache
def load() -> Rules:
    return Rules.parse(RULES_FILE.read_text(encoding="utf-8"))


def floor(command: str) -> str | None:
    """The floor rule `command` breaks, or None."""
    return load().refuses(command or "")


__all__ = ["RULES_FILE", "Rule", "RuleError", "Rules", "floor", "load"]
