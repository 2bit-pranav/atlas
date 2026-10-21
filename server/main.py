"""ASGI entry point: `uvicorn server.main:app --port <backend>`.

Run it through `atlas start`, which sets ATLAS_ROOT and ATLAS_SETTINGS and
never passes `--reload`. With `--reload`, uvicorn's worker runs on the
Selector event loop, which cannot start subprocesses on Windows -- every shell
call, and therefore every skill, fails with a blank NotImplementedError.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Subprocesses need the Proactor loop on Windows. Set before uvicorn makes one.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Logs can contain any character a model writes. Never let the console's code
# page turn one into an exception (started by hand, PYTHONUTF8 may be unset).
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

import logging  # noqa: E402

# Atlas's own log lines (`agent.*`, `server.*`) in a form `atlas start` can
# read; uvicorn's loggers keep their own handlers and do not propagate.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "strands", "mcp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from server.app import create_app  # noqa: E402

app = create_app(os.environ.get("ATLAS_SETTINGS"))

__all__ = ["app"]
