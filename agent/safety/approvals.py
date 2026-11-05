"""The shape of the function that asks the user (the run's `request_approval`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

#: `(kind, detail) -> "allowed" | "denied" | "expired"`
Approver = Callable[[str, dict[str, Any]], Awaitable[str]]


__all__ = ["Approver"]
