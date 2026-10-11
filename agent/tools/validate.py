"""Argument validation that teaches (spec section 11.1, principle 3).

"Validate, then teach." A tool that says `sheet "Q5" not found; available:
Q1..Q4` fixes the model's next attempt. A tool that says `invalid argument`
sends a 2B model in a circle.

So every failure here carries the valid options, and nothing raises a bare
``KeyError`` at the model.
"""

from __future__ import annotations

from typing import Any, Iterable

from agent.tools.contract import ToolError


def require(ctx: Any, value: Any, name: str, valid: Iterable[Any] = ()) -> Any:
    """A value the tool cannot work without."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError("bad_arg", f"{name} is required", _names(valid))
    return value


def one_of(value: str, valid: list[str], name: str) -> str:
    """A value from a fixed set. Never guess on the model's behalf."""
    if value not in valid:
        raise ToolError(
            "bad_arg", f"{name} {value!r} is not one of the options", valid
        )
    return value


def positive_int(value: Any, name: str, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError("bad_arg", f"{name} must be a whole number, got {value!r}") from None
    if number < 0 or (maximum is not None and number > maximum):
        bound = f"0..{maximum}" if maximum is not None else ">= 0"
        raise ToolError("bad_arg", f"{name} must be {bound}, got {number}")
    return number


def clamp_int(value: Any, name: str, low: int, high: int, default: int) -> int:
    """Like ``positive_int`` but forgiving, for optional tuning arguments."""
    if value is None:
        return default
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _names(values: Iterable[Any]) -> list[str]:
    return [str(v) for v in values]


__all__ = ["clamp_int", "one_of", "positive_int", "require"]
