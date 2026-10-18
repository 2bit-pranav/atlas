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

from server.app import create_app  # noqa: E402

app = create_app(os.environ.get("ATLAS_SETTINGS"))

__all__ = ["app"]
