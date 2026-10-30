"""What counts as an install command (asked before it runs)."""

from __future__ import annotations

import re

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


__all__ = ["is_install"]
