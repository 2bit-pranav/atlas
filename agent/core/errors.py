"""Typed errors for the persistence layer (spec section 6).

Each one carries the HTTP status and the stable error code the API layer should
return, so the mapping lives with the rule that raises it rather than being
re-derived in every endpoint.
"""

from __future__ import annotations


class AtlasError(Exception):
    """Base class: everything the API layer can turn into a clean response."""

    status_code = 500
    code = "internal"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class NotFound(AtlasError):
    status_code = 404
    code = "not_found"


class BadRequest(AtlasError):
    status_code = 422
    code = "bad_arg"


class RunActive(AtlasError):
    """A run is already going; Atlas allows exactly one at a time (section 2).

    Raised by letting the partial unique index fail rather than by a read-then-
    write check, so two concurrent starts cannot both win.
    """

    status_code = 409
    code = "run_active"


class ParentNotAccepting(AtlasError):
    """The visible leaf cannot receive a new message.

    A cancelled or failed assistant node stays in the tree so it can be retried,
    but per section 6 it cannot be a parent for a new message in v1.
    """

    status_code = 422
    code = "parent_not_completed"


class RunFinished(AtlasError):
    """The run already reached a terminal state."""

    status_code = 409
    code = "run_finished"


class TerminalEventExists(AtlasError):
    """Section 8: exactly one terminal event per run."""

    status_code = 409
    code = "terminal_event_exists"


__all__ = [
    "AtlasError",
    "BadRequest",
    "NotFound",
    "ParentNotAccepting",
    "RunActive",
    "RunFinished",
    "TerminalEventExists",
]
