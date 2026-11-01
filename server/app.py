"""The HTTP API. Chats, turns, runs, settings -- all under `/api`.

One active run at a time, a run that outlives the frontend, and a chat tree
whose model history lives in Strands snapshots.

    send    a turn under the selected leaf, restoring the parent's after_snap
    retry   last turn only: a sibling with the same parent and restore point,
            sampled wider and told what the earlier versions said
    edit    any turn: delete it, its versions and everything below, then run
            the new text from the same restore point
    <  />   select another version at a position; nothing is recomputed
    cancel  agent.cancel(); the turn keeps its partial transcript but no
            snapshot, so it can never become the parent of a follow-up

Everything is under `/api` so the frontend can own `/settings`, `/skills` and
`/mcp` as page paths without the dev proxy forwarding them to the backend.
"""


from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from agent.config import paths
from server.routes.chats import register as register_chats
from server.routes.extension import register as register_extension
from server.routes.files import register as register_files
from server.routes.health import register as register_health
from server.routes.runs import register as register_runs
from server.routes.settings import register as register_settings
from server.routes.spa import _serve_client
from server.routes.turns import register as register_turns
from server.security import Pairing, guard, trusted_origins
from server.state import Atlas

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------- app --


def create_app(settings_path: str | Path | None = None) -> FastAPI:
    state = Atlas(paths.resolve(settings_path or "settings.json"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop = asyncio.get_running_loop()
        if sys.platform == "win32" and "Proactor" not in type(loop).__name__:
            # The Selector loop cannot start subprocesses (see server/main.py).
            # `uvicorn --reload` is the usual cause.
            logger.error("running on %s: shell tools will not work. Start the backend "
                         "with `atlas start`, or uvicorn WITHOUT --reload.",
                         type(loop).__name__)
        # Connected in the background: a slow `npx` download must not hold up
        # the API, and a chat started meanwhile simply has no MCP tools yet.
        loop.run_in_executor(None, state.mcp.start_all)
        yield
        for run in list(state.runs._runs.values()):  # noqa: SLF001
            if run.task and not run.task.done():
                state.runs.cancel(run.id)
        state.close()

    app = FastAPI(title="Atlas", lifespan=lifespan)
    app.state.atlas = state
    pairing = Pairing(paths.data_dir(state.settings) / "pairing-token")
    ports = state.boot.ports
    trusted = trusted_origins(ports, dev=bool(os.environ.get("ATLAS_DEV_UI")))
    app.middleware("http")(guard(pairing, trusted))
    api = APIRouter(prefix="/api")

    register_extension(api, state, pairing, ports)
    register_health(api, state)
    register_chats(api, state)
    register_files(api, state)
    register_turns(api, state)
    register_runs(api, state)
    settings_view = register_settings(api, state)

    app.state.settings_view = settings_view
    app.include_router(api)

    # Skills and MCP routes, also under /api.
    from server.routes.integrations import register as register_extensions  # noqa: PLC0415

    register_extensions(app, state)
    _serve_client(app)
    return app


__all__ = ["create_app"]
