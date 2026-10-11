"""The tool result contract (spec section 11.5).

Every tool returns exactly one of two things, and the model sees a one-line
rendering of it:

    ok: <summary>
    error[code]: <message>. valid: a, b, c

That is deliberately the whole interface. The model gets a short sentence, not a
JSON payload it has to parse, which matters for a 2B model.

Strands passes a dict with ``status`` and ``content`` through unchanged (this is
spike S5: the shape is under our control, so ``is_error`` is deterministic
rather than inferred from an exception), so these render straight into the tool
result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Error codes the model may see. A closed set, so the client can rely on it.
CODES = ("not_found", "bad_arg", "too_large", "not_ready", "not_loaded", "failed")


@dataclass
class ToolOutput:
    """A successful result.

    ``objects`` are ids created by this call. They are registered in the catalog
    by the runtime before the result is rendered, so the model can refer to
    them on the next step.
    """

    summary: str
    objects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Structured body, kept out of the model's view and offloaded to an object.
    data: Any = None

    def render(self) -> str:
        text = f"ok: {self.summary}"
        if self.warnings:
            text += "\n  warn: " + "; ".join(self.warnings)
        return text

    def to_result(self) -> dict[str, Any]:
        return {"status": "success", "content": [{"text": self.render()}]}


@dataclass
class ToolError(Exception):
    """A failed result. ``valid`` is what makes errors teach rather than nag.

    An ``Exception`` as well as a value: tools raise it (that is the natural
    way to write an early return), and :func:`agent.tools.guard.guarded` turns
    it into the rendering below before Strands ever sees it. Nothing else may
    catch it.
    """

    code: str
    message: str
    valid: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.code not in CODES:
            # A typo here would put an unknown code in front of the model.
            raise ValueError(f"unknown error code {self.code!r}; use one of {CODES}")

    def render(self) -> str:
        text = f"error[{self.code}]: {self.message}"
        if self.valid:
            text += ". valid: " + ", ".join(str(v) for v in self.valid)
        return text

    def to_result(self) -> dict[str, Any]:
        return {"status": "error", "content": [{"text": self.render()}]}


def is_error(result: dict[str, Any]) -> bool:
    return result.get("status") == "error"


def result_text(result: dict[str, Any]) -> str:
    parts = result.get("content") or []
    return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))


__all__ = ["CODES", "ToolError", "ToolOutput", "is_error", "result_text"]
