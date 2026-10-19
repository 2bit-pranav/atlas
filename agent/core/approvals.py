"""Recognising installs, and the shape of the function that asks the user.

A shell command that installs anything (pip, npm, npx, uv, winget, ...) is
never run without the user's Allow. The asking itself is a step of the tool
policy (`policy.py`); this module only decides what counts as an install.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable


#: `(kind, detail) -> "allowed" | "denied" | "expired"`
Approver = Callable[[str, dict[str, Any]], Awaitable[str]]

#: A command that installs something, at the start of the command or after a
#: separator (`cd x && npm install y`).
_INSTALL = re.compile(
    r"(?:^|[;&|(]\s*|\bsudo\s+)"
    r"(?:"
    r"(?:python3?|py)(?:\.exe)?\s+-m\s+pip\s+install"
    r"|pip3?(?:\.exe)?\s+install"
    r"|uv\s+(?:pip\s+install|add|tool\s+install)"
    r"|uvx\b"
    r"|npm\s+(?:i|install|add|ci)\b"
    r"|npx\b"
    r"|pnpm\s+(?:add|install|i|dlx)\b"
    r"|yarn\s+(?:add|global\s+add|dlx)\b"
    r"|bunx?\s+(?:add|install|i)?\b"
    r"|conda\s+install|mamba\s+install"
    r"|winget\s+install|choco\s+install|scoop\s+install"
    r"|apt(?:-get)?\s+install|brew\s+install"
    r"|cargo\s+install|go\s+install|gem\s+install"
    r")",
    re.IGNORECASE,
)


def is_install(command: str) -> bool:
    return bool(_INSTALL.search(command or ""))


__all__ = ["Approver", "is_install"]
