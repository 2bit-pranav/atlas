"""Exception -> stable error code (spec section 8, rule 6).

One function owns the mapping so the run executor never invents a code inline
and the client can rely on a closed set:

``llama_unreachable``, ``context_overflow``, ``tool_failed``, ``cancelled``,
``internal``, plus ``run_failed`` for a malformed tool call (section 9.1).
"""

from __future__ import annotations

import httpx
from strands.types.exceptions import (
    ContextWindowOverflowException,
    ModelThrottledException,
)

CODE_LLAMA_UNREACHABLE = "llama_unreachable"
CODE_CONTEXT_OVERFLOW = "context_overflow"
CODE_CANCELLED = "cancelled"
CODE_INTERNAL = "internal"
CODE_THROTTLED = "llama_busy"


def map_exception(exc: BaseException) -> dict[str, object]:
    """A ``{"code", "message", "retryable"}`` dict, as section 8 specifies."""
    if isinstance(exc, ContextWindowOverflowException):
        return {
            "code": CODE_CONTEXT_OVERFLOW,
            "message": str(exc) or "the prompt no longer fits the context window",
            "retryable": False,
        }
    if isinstance(exc, ModelThrottledException):
        return {
            "code": CODE_THROTTLED,
            "message": str(exc) or "the model server is busy",
            "retryable": True,
        }
    if isinstance(exc, httpx.HTTPError):
        return {
            "code": CODE_LLAMA_UNREACHABLE,
            "message": f"could not reach the model server: {exc}",
            "retryable": True,
        }
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return {
            "code": CODE_LLAMA_UNREACHABLE,
            "message": str(exc) or "connection to the model server failed",
            "retryable": True,
        }
    return {
        "code": CODE_INTERNAL,
        "message": f"{type(exc).__name__}: {exc}",
        "retryable": False,
    }


def is_cancel(exc: BaseException) -> bool:
    """Cancellation arrives as asyncio.CancelledError or our own marker."""
    import asyncio

    return isinstance(exc, (asyncio.CancelledError, RunCancelled))


class RunCancelled(Exception):
    """Raised internally when a run is cancelled."""


__all__ = [
    "CODE_CANCELLED",
    "CODE_CONTEXT_OVERFLOW",
    "CODE_INTERNAL",
    "CODE_LLAMA_UNREACHABLE",
    "RunCancelled",
    "is_cancel",
    "map_exception",
]
