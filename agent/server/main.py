"""FastAPI backend (spec section 14).

Endpoints from section 14, plus the two chat endpoints L3 needs in order to be
usable at all (there is no "create a chat" in the table, but there is no way to
have one without it).

    POST   /chats                        create a chat
    GET    /chats                        list chats
    POST   /chats/{id}/messages          send -> run_id (409 active, 422 not ready)
    POST   /nodes/{id}/edit              edit  -> run_id
    POST   /nodes/{id}/retry             retry -> run_id
    POST   /nodes/{id}/select            switch version
    GET    /chats/{id}/tree              visible path + sibling counts
    GET    /chats/{id}/objects           catalog
    GET    /runs/active                  the single active run
    GET    /runs/{id}                    status snapshot
    GET    /runs/{id}/events?after=seq   SSE with replay
    POST   /runs/{id}/cancel             cancel

Startup calls ``Repo.recover_interrupted`` so a run left active by a crash
becomes ``interrupted`` rather than blocking the app forever (section 7).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.cli.settings import SettingsError, load_settings
from agent.core import Database, Repo
from agent.core.errors import AtlasError, RunFinished, RunActive
from agent.core.migrations import migrate
from agent.core.paths import resolve_data_dir
from agent.ingest import AttachmentStore, IngestService, IngestWorker
from agent.models import AtlasLlamaCppModel
from agent.run import Broadcaster, ContextBuilder, EventSink, RunExecutor
from agent.tools.runtime import ToolRuntime

logger = logging.getLogger("agent.server")

STATIC_DIR = Path(__file__).parent / "static"
SETTINGS_TIERS = None  # populated at startup


# ------------------------------------------------------------------- models --


class CreateChat(BaseModel):
    title: str | None = None


class SendMessage(BaseModel):
    text: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


class EditNode(BaseModel):
    text: str | None = None
    attachment_ids: list[str] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------- app state --


class Services:
    """Everything a request needs, built once at startup."""

    def __init__(self) -> None:
        self.db: Database | None = None
        self.repo: Repo | None = None
        self.broadcaster = Broadcaster()
        self.executor: RunExecutor | None = None
        self.ingest: Any = None
        self.settings: Any = None

    def require_repo(self) -> Repo:
        if self.repo is None:
            raise HTTPException(503, "database is not ready")
        return self.repo

    def require_executor(self) -> RunExecutor:
        if self.executor is None:
            raise HTTPException(503, "run engine is not ready")
        return self.executor

    def require_ingest(self) -> Any:
        if self.ingest is None:
            raise HTTPException(503, "ingestion is not ready")
        return self.ingest


services = Services()


def _model_factory(base_url: str, params: dict[str, Any]) -> Any:
    """Build the per-run model.

    ``ATLAS_FAKE_MODEL=1`` swaps in the scripted model so the test suite and
    evals are deterministic and need no GPU (section 19 ground rules).
    """
    if os.environ.get("ATLAS_FAKE_MODEL") == "1":
        from agent.run.fake_model import FakeModel

        delay = float(os.environ.get("ATLAS_FAKE_DELAY", "0"))

        def fake() -> Any:
            return FakeModel(delay=delay)

        return fake

    def factory() -> AtlasLlamaCppModel:
        return AtlasLlamaCppModel(
            base_url=base_url, params=dict(params), use_native_token_count=True
        )

    return factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = resolve_data_dir()
    db_path = Path(os.environ.get("ATLAS_DB") or (data_dir / "atlas.db"))
    services.db = Database(db_path)
    migrate(services.db.connection)
    services.repo = Repo(services.db)

    settings = None
    settings_path = Path(os.environ.get("ATLAS_SETTINGS", "settings.json"))
    if settings_path.exists():
        try:
            settings = load_settings(settings_path)
            services.settings = settings
        except SettingsError as exc:
            logger.warning("could not load %s: %s", settings_path, exc)

    base_url = (
        f"http://127.0.0.1:{settings.ports.llama}" if settings else "http://127.0.0.1:8080"
    )
    params = (
        {
            "temperature": settings.sampling.temperature,
            "top_p": settings.sampling.top_p,
            "top_k": settings.sampling.top_k,
            "max_tokens": settings.sampling.max_tokens,
        }
        if settings
        else {"temperature": 0.7, "max_tokens": 2048}
    )

    # Startup recovery (section 7): anything still active cannot have a live
    # executor, because the process that owned it is gone.
    recovered = services.repo.recover_interrupted()
    if recovered:
        logger.warning("marked %d leftover run(s) interrupted: %s", len(recovered), recovered)

    # The tool runtime is built once and reused: the tool *set* is fixed (so the
    # prompt prefix stays byte-stable and llama's cache survives, spec 10), while
    # each run gets its own ToolContext through invocation_state.
    tool_runtime = ToolRuntime(
        services.repo,
        workspace_root=data_dir / "workspace",
        settings=settings.model_dump() if settings else {},
    )

    services.executor = RunExecutor(
        services.repo,
        services.broadcaster,
        _model_factory(base_url, params),
        context_builder=ContextBuilder(services.repo),
        system_prompt=settings.system_prompt if settings else None,
        tool_runtime=tool_runtime,
    )

    logger.info("backend ready (db=%s, model=%s)", db_path, base_url)

    # Ingestion runs in its own single-worker process and is independent of the
    # run lock (section 2), so a parse and a run can overlap.
    worker = IngestWorker(db_path, workspace_root=data_dir / "workspace")
    requeued = worker.requeue_running()
    if requeued:
        logger.warning("re-queued %d interrupted extraction(s)", len(requeued))
    services.ingest = IngestService(services.db, worker, workspace_root=data_dir / "workspace")

    yield

    worker.stop()
    if services.executor:
        await services.executor.shutdown()
    if services.db:
        services.db.close()


app = FastAPI(title="Atlas on Strands", lifespan=lifespan)


# ----------------------------------------------------------------- errors ----


@app.exception_handler(AtlasError)
async def atlas_error_handler(request: Request, exc: AtlasError) -> Any:
    """Typed persistence errors already know their status and code."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_payload()})


# ------------------------------------------------------------------ chats ----


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus the one thing a launcher really wants to know."""
    ready = services.repo is not None and services.executor is not None
    active = services.repo.active_run() if services.repo else None
    return {
        "status": "ok" if ready else "starting",
        "db": str(services.db.path) if services.db else None,
        "active_run": active.id if active else None,
        "subscribers": services.broadcaster.subscriber_count(),
    }


@app.get("/chats")
def list_chats() -> dict[str, Any]:
    repo = services.require_repo()
    return {"chats": [
        {"id": c.id, "title": c.title, "created_at": c.created_at,
         "updated_at": c.updated_at}
        for c in repo.list_chats()
    ]}


@app.post("/chats")
def create_chat(body: CreateChat | None = Body(default=None)) -> dict[str, Any]:
    repo = services.require_repo()
    chat = repo.create_chat(body.title if body else None)
    return {"id": chat.id, "title": chat.title, "root_id": chat.root_id}


@app.get("/chats/{chat_id}")
def get_chat(chat_id: str) -> dict[str, Any]:
    repo = services.require_repo()
    chat = repo.get_chat(chat_id)
    return {"id": chat.id, "title": chat.title, "created_at": chat.created_at,
            "updated_at": chat.updated_at}


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str) -> dict[str, Any]:
    repo = services.require_repo()
    repo.get_chat(chat_id)
    with repo.db.write() as conn:
        conn.execute(
            "UPDATE chats SET deleted_at=? WHERE id=?", (_ms(), chat_id)
        )
    return {"deleted": chat_id}


@app.get("/chats/{chat_id}/attachments")
def list_attachments(chat_id: str) -> dict[str, Any]:
    """Every attachment on this chat, with its ingestion status."""
    repo = services.require_repo()
    store = AttachmentStore(repo.db)
    return {
        "attachments": [store.status(a["id"]) for a in store.attachments_for_chat(chat_id)]
    }


@app.post("/chats/{chat_id}/attachments")
async def upload_attachment(chat_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload and queue a parse. Returns the handle and status=queued at once.

    The caller never waits on the parse: it gets a handle immediately and polls
    ``GET /attachments/{id}`` until the extraction reaches ``ready``.
    """
    service = services.require_ingest()
    data = await file.read()
    return service.upload(chat_id, file.filename or "upload", data, file.content_type)


@app.get("/attachments/{attachment_id}")
def get_attachment(attachment_id: str) -> dict[str, Any]:
    """Status, progress, embed_status, warnings and outline (section 14)."""
    return services.require_ingest().status(attachment_id)


@app.post("/attachments/{attachment_id}/retry")
def retry_attachment(attachment_id: str, chat_id: str = Query(...)) -> dict[str, Any]:
    """Re-run a failed parse."""
    return services.require_ingest().retry(attachment_id, chat_id)


@app.get("/attachments/{attachment_id}/search")
def search_attachment(attachment_id: str, q: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Keyword search restricted to one attachment."""
    repo = services.require_repo()
    attachment = AttachmentStore(repo.db).attachment(attachment_id)
    hits = services.require_ingest().search(q, target=attachment["handle"], limit=8)
    return {"query": q, "handle": attachment["handle"], "hits": hits}


# ------------------------------------------------------------------ tree -----


@app.get("/chats/{chat_id}/tree")
def get_tree(chat_id: str) -> dict[str, Any]:
    """Visible path with sibling counts, for the `<` `>` version switch."""
    repo = services.require_repo()
    nodes = []
    for item in repo.tree_with_siblings(chat_id):
        node = item.node
        run_status = None
        if node.run_id:
            run_status = repo.get_run(node.run_id).status
        nodes.append({
            "id": node.id,
            "role": node.role,
            "parent_id": node.parent_id,
            "selected_child_id": node.selected_child_id,
            "run_id": node.run_id,
            "run_status": run_status,
            "sibling_count": item.sibling_count,
            "sibling_index": item.sibling_index,
            "created_at": node.created_at,
            "text": _node_text(node),
            "steps": [
                {"id": s.id, "idx": s.idx, "kind": s.kind, "content": s.content,
                 "call_id": s.call_id, "is_error": s.is_error, "status": s.status}
                for s in repo.steps(node.id)
            ],
        })
    return {"chat_id": chat_id, "path": nodes}


@app.get("/chats/{chat_id}/objects")
def get_objects(chat_id: str) -> dict[str, Any]:
    repo = services.require_repo()
    return {"objects": [
        {"id": o.id, "name": o.name, "kind": o.kind, "store": o.store,
         "row_count": o.row_count, "tokens": o.tokens, "created_at": o.created_at}
        for o in repo.objects(chat_id)
    ]}


# ------------------------------------------------------------------- runs ----


def _start(repo: Repo, **kwargs: Any) -> dict[str, Any]:
    """Create the run then hand it to the executor."""
    run = repo.start_run(**kwargs)
    executor = services.require_executor()
    executor.start(run)
    return {"run_id": run.id, "chat_id": run.chat_id, "status": run.status}


@app.post("/chats/{chat_id}/messages")
async def send_message(chat_id: str, body: SendMessage) -> dict[str, Any]:
    """Send. 409 when a run is active, 422 when an attachment is not ready.

    ``async def`` on purpose: the executor schedules an asyncio task, so these
    must run on the event loop. A sync ``def`` would be dispatched to a
    threadpool where ``asyncio.create_task`` has no running loop.
    """
    repo = services.require_repo()
    return _start(
        repo,
        chat_id=chat_id,
        text=body.text,
        attachment_ids=tuple(body.attachment_ids),
        options=body.options,
        settings_snapshot=services.settings.model_dump(mode="json")
        if services.settings
        else None,
        launch_id=_launch_id(),
        origin="send",
    )


@app.post("/nodes/{node_id}/edit")
async def edit_node(node_id: str, body: EditNode) -> dict[str, Any]:
    repo = services.require_repo()
    node = repo.get_node(node_id)
    return _start(
        repo,
        chat_id=node.chat_id,
        text=body.text,
        attachment_ids=tuple(body.attachment_ids or ()),
        options=body.options,
        settings_snapshot=services.settings.model_dump(mode="json")
        if services.settings
        else None,
        launch_id=_launch_id(),
        origin="edit",
        edit_node_id=node_id,
    )


@app.post("/nodes/{node_id}/retry")
async def retry_node(node_id: str, body: EditNode | None = Body(default=None)) -> dict[str, Any]:
    repo = services.require_repo()
    node = repo.get_node(node_id)
    options = body.options if body else {}
    return _start(
        repo,
        chat_id=node.chat_id,
        options=options,
        settings_snapshot=services.settings.model_dump(mode="json")
        if services.settings
        else None,
        launch_id=_launch_id(),
        origin="retry",
        retry_node_id=node_id,
    )


@app.post("/nodes/{node_id}/select")
def select_node(node_id: str) -> dict[str, Any]:
    """Switch versions. No run."""
    repo = services.require_repo()
    node = repo.select(node_id)
    return {"selected": node.id, "parent_id": node.parent_id}


@app.get("/runs/active")
def get_active_run() -> dict[str, Any]:
    repo = services.require_repo()
    run = repo.active_run()
    if run is None:
        return {"run": None}
    return {"run": _run_dict(run)}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    repo = services.require_repo()
    return _run_dict(repo.get_run(run_id))


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    """The only way to stop a run (section 7)."""
    repo = services.require_repo()
    executor = services.require_executor()
    run = repo.get_run(run_id)
    if not run.is_active:
        raise RunFinished(f"run {run_id} is {run.status}", run_id=run_id,
                          status=run.status)
    updated = repo.request_cancel(run_id)
    # Tell every attached client before winding down.
    sink = EventSink(repo, services.broadcaster, run_id)
    sink.emit("cancel_requested", {})
    await executor.cancel(run_id)
    return {"run_id": run_id, "status": updated.status}


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str, after: int = Query(0, ge=0)) -> Any:
    """SSE with replay (section 8, rule 4).

    Order matters: subscribe to the live feed *first*, then read the rows we
    missed, so no event can slip through the gap between the two. Duplicates
    are dropped by comparing seq.
    """
    repo = services.require_repo()
    run = repo.get_run(run_id)
    broadcaster = services.broadcaster

    async def generator():
        queue = broadcaster.subscribe()
        try:
            last = after

            # Replay first. Anything the live feed already delivered is deduped.
            for event in repo.events(run_id, after=last):
                envelope = _envelope(event)
                if envelope.seq <= last:
                    continue
                last = envelope.seq
                yield _frame(envelope)
                if envelope.type in ("run_completed", "run_failed", "run_cancelled"):
                    return

            # Then follow live.
            while True:
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    if repo.get_run(run_id).status not in (
                        "running", "cancelling"
                    ):
                        # Terminal event was written between frames.
                        for event in repo.events(run_id, after=last):
                            envelope = _envelope(event)
                            if envelope.seq > last:
                                last = envelope.seq
                                yield _frame(envelope)
                        return
                    continue

                if envelope.run_id != run_id or envelope.seq <= last:
                    continue
                last = envelope.seq
                yield _frame(envelope)
                if envelope.type in ("run_completed", "run_failed", "run_cancelled"):
                    return
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ----------------------------------------------------------------- static ----

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> Any:
    page = STATIC_DIR / "index.html"
    if page.exists():
        return FileResponse(str(page))
    return {"service": "atlas", "docs": "/docs"}


# ----------------------------------------------------------------- helpers ---


def _ms() -> int:
    from agent.ids import now_ms

    return now_ms()


def _launch_id() -> str | None:
    path = Path("launched.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("launch_id")
    except (OSError, json.JSONDecodeError):
        return None


def _run_dict(run: Any) -> dict[str, Any]:
    return {
        "id": run.id, "chat_id": run.chat_id, "status": run.status,
        "origin": run.origin, "user_node_id": run.user_node_id,
        "assistant_node_id": run.assistant_node_id, "last_seq": run.last_seq,
        "started_at": run.started_at, "finished_at": run.finished_at,
        "usage": run.usage, "error": run.error, "launch_id": run.launch_id,
    }


def _envelope(event: Any) -> Any:
    from agent.run.events import Envelope

    return Envelope(
        run_id=event.run_id, seq=event.seq, ts=event.ts,
        type=event.type, data=event.payload,
    )


def _frame(envelope: Any) -> str:
    return f"id: {envelope.seq}\ndata: {json.dumps({'run_id': envelope.run_id, 'seq': envelope.seq, 'ts': envelope.ts, 'type': envelope.type, 'data': envelope.data, 'agent': envelope.agent}, ensure_ascii=False)}\n\n"


def _node_text(node: Any) -> str:
    content = node.content if isinstance(node.content, dict) else {}
    return "\n\n".join(
        str(b.get("text", ""))
        for b in content.get("blocks", []) or []
        if isinstance(b, dict) and b.get("type") == "text"
    )


__all__ = ["app", "services"]
