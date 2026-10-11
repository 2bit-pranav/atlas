"""Turning anything a tool can do wrong into the contract's rendering.

Tools raise :class:`ToolError` because that is the natural way to write them.
Strands would then hand the model ``Error: ToolError - error[bad_arg]: ...``,
which leaks a Python class name and a prefix the model has to read past on
every retry.

``@guarded`` sits between the tool and Strands and normalises the outcome to
exactly the two renderings in :mod:`agent.tools.contract`:

    ok: ...
    error[code]: ...

Applied *under* ``@tool``, so the generated schema still comes from the real
signature (``inspect.signature`` follows ``__wrapped__``).
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable, TypeVar

from agent.tools.contract import ToolError

F = TypeVar("F", bound=Callable[..., Any])


def guarded(func: F) -> F:
    """Catch every failure and render it as the model contract requires."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except ToolError as exc:
            return exc.to_result()
        except Exception as exc:  # noqa: BLE001 - a tool must never crash a run
            return ToolError("failed", f"{type(exc).__name__}: {exc}").to_result()

    return wrapper  # type: ignore[return-value]


def with_timeout(seconds: float) -> Callable[[F], F]:
    """Run a tool under a wall-clock limit (spec 9: cancel + timeout).

    DuckDB's own ``statement_timeout`` covers SQL; this covers everything else,
    which is the only reason a stuck tool cannot hold a run open forever.
    """

    def decorate(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result: dict[str, Any] = {}

            worker = threading.Thread(
                target=lambda: result.update(guarded(func)(*args, **kwargs)),
                daemon=True,
            )
            worker.start()
            worker.join(seconds)
            if worker.is_alive():
                return ToolError(
                    "failed", f"{func.__name__} exceeded {seconds:.0f}s"
                ).to_result()
            return result

        return wrapper  # type: ignore[return-value]

    return decorate


__all__ = ["guarded", "with_timeout"]
