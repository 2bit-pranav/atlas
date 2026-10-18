"""ASGI entry point.

`uvicorn server.main:app --port <backend>` reads settings.json from the
working directory. The CLI passes `--port` from the same file, so both agree.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import asyncio

# Ensure Windows uses the Proactor event loop for subprocess support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from server.app import create_app

app = create_app(
    settings_path=os.environ.get("ATLAS_SETTINGS", "settings.json"),
    root=os.environ.get("ATLAS_ROOT", "."),
)

__all__ = ["app"]