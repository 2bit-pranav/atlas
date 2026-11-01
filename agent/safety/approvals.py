"""Recognising installs, and the shape of the function that asks the user.

A shell command that installs anything (pip, npm, npx, uv, winget, ...) is
never run without the user's Allow. The asking itself is a step of the tool
policy (`policy.py`); this module only decides what counts as an install.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

#: `(kind, detail) -> "allowed" | "denied" | "expired"`
Approver = Callable[[str, dict[str, Any]], Awaitable[str]]


__all__ = ["Approver"]
