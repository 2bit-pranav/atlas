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
`/mcp` as pages: the dev proxy used to forward `/settings` to the backend,
which would have swallowed the settings page.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.core import paths
from agent.core.agent_factory import RetryPlan, build_agent, retry_hint
from agent.core.chats import (
    CANCELLED,
    COMPLETED,
    FAILED,
    RUNNING,
    ChatStore,
    TreeError,
)
from agent.core.memory_manager import MemoryManager
from agent.core.session_manager import SessionManager
from agent.core.settings import (
    TIERS,
    Settings,
    SettingsError,
    Tier,
    changed_restart_keys,
    flatten,
    load_settings,
    parse_settings,
    restart_tier_values,
    set_path,
    write_settings,
)
from agent.core.skill_manager import SkillManager
from agent.core.tool_manager import ToolManager
from server.events import _aiter, translate
from server.runs import Run, RunConflict, RunManager
from server.transcript import answer_of

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------- models --


class CreateChat(BaseModel):
    title: str = ""


class RenameChat(BaseModel):
    title: str


class SendMessage(BaseModel):
    text: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    thinking: bool | None = None


class RetryTurn(BaseModel):
    thinking: bool | None = None


class EditTurn(BaseModel):
    text: str
    files: list[dict[str, Any]] | None = None
    thinking: bool | None = None


class SelectTurn(BaseModel):
    delta: int = 0


# ------------------------------------------------------------------ state --


class Atlas:
    """The backend's state, held outside the app for testability."""

    def __init__(self, settings_path: Path) -> None:
        self.settings_path = Path(settings_path)
        #: As the process started. Restart-tier keys keep these values for the
        #: life of the process even after settings.json changes, because the
        #: running llama-server was built with them.
        self.boot = load_settings(self.settings_path)
        self.settings = self.boot
        self.store = ChatStore(paths.database(self.settings))
        self.runs = RunManager()
        if n := self.store.mark_interrupted():
            logger.info("%d turn(s) left running by a previous process are now interrupted", n)
        logger.info("backend ready (root=%s, db=%s)", paths.ROOT, self.store.db_path)

    def close(self) -> None:
        self.store.close()

    # ------------------------------------------------------------ helpers --

    def require_chat(self, chat_id: str) -> dict[str, Any]:
        chat = self.store.get_chat(chat_id)
        if chat is None:
            raise HTTPException(404, f"no chat {chat_id}")
        return chat

    def require_turn(self, turn_id: str) -> dict[str, Any]:
        turn = self.store.get_turn(turn_id)
        if turn is None:
            raise HTTPException(404, f"no turn {turn_id}")
        return turn

    def chat_dir(self, chat_id: str) -> Path:
        path = paths.chat_dir(self.settings, chat_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_run_slot(self) -> None:
        try:
            self.runs.ensure_available()
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    def thinking(self, override: bool | None) -> bool:
        return self.settings.sampling.thinking if override is None else override

    def view(self, chat_id: str) -> dict[str, Any]:
        """The visible path with everything the UI needs to draw it. No snapshots read."""
        chat = self.require_chat(chat_id)
        run = self.runs.active_for_chat(chat_id)
        turns = []
        for turn in self.store.path(chat_id):
            versions = [v["id"] for v in self.store.siblings_of(turn["id"])]
            turns.append(_turn_view(turn, versions))
        return {**chat, "turns": turns, "active_run": _run_view(run) if run else None}

    # -------------------------------------------------------------- runs --

    def launch(
        self, turn: dict[str, Any], *, thinking: bool, retry: RetryPlan | None = None,
    ) -> Run:
        try:
            run = self.runs.start(turn["chat_id"], turn["id"],
                                  context_size=self.settings.model.context_size)
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        run.task = asyncio.create_task(self.execute(run, turn, thinking=thinking, retry=retry))
        return run

    async def execute(
        self, run: Run, turn: dict[str, Any], *, thinking: bool, retry: RetryPlan | None,
    ) -> None:
        """The run body. One task per run; the frontend is not involved."""
        settings = self.settings
        files = json.loads(turn["files_json"] or "[]")
        text = _agent_text(turn["user_text"], files)
        hint = retry_hint(settings, retry) if retry else ""
        sm = SessionManager(settings, run.chat_id)
        try:
            manager = sm.manager()
            # Building restores a snapshot from disk and constructs the harness:
            # blocking work that used to stall every SSE stream while it ran.
            agent = await asyncio.to_thread(
                build_agent, settings, chat_id=run.chat_id, thinking=thinking,
                restore_snapshot_id=turn["before_snap"], session_manager=manager,
                retry=retry, observer=run.observe,
            )
            run.agent = agent
            if run.cancel.is_set():
                raise asyncio.CancelledError
            run.emit({"type": "run_started", "chat_id": run.chat_id, "turn_id": run.turn_id})

            start = len(agent.messages)
            prompt = f"{text}\n\n{hint}" if hint else text
            async for out in translate(_aiter(agent.stream_async(prompt))):
                if run.cancel.is_set():
                    raise asyncio.CancelledError
                run.emit(out)

            if hint:
                _strip_hint(agent.messages, start, hint)
            snap = await manager.save_snapshot(agent, is_latest=False)
            self._finish(run, COMPLETED, after_snap=snap)

        except (asyncio.CancelledError, KeyboardInterrupt):
            # No snapshot: a cancelled turn can be retried or edited, never
            # continued, so a half-finished tool call is never built upon.
            self._finish(run, CANCELLED)

        except Exception as exc:  # noqa: BLE001
            logger.exception("run %s failed", run.id)
            self._finish(run, FAILED, error=f"{type(exc).__name__}: {exc}")

        finally:
            run.agent = None
            self.runs.adopt(run)

    def _finish(self, run: Run, status: str, *, after_snap: str | None = None,
                error: str | None = None) -> None:
        stats = run.transcript.final_stats()
        try:
            self.store.finish_turn(run.turn_id, status, after_snap=after_snap,
                                   render=run.transcript.parts, stats=stats, error=error)
            self.store.touch(run.chat_id)
        except Exception:  # noqa: BLE001 - the turn may have been cut by an edit
            logger.exception("could not record the end of turn %s", run.turn_id)
        run.finish(status, error)


# -------------------------------------------------------------------- app --


def create_app(settings_path: str | Path | None = None) -> FastAPI:
    state = Atlas(paths.resolve(settings_path or "settings.json"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop = asyncio.get_running_loop()
        if sys.platform == "win32" and "Proactor" not in type(loop).__name__:
            # Subprocesses are unsupported on the Selector loop, so every shell
            # call (and so every skill) would fail with a blank
            # NotImplementedError. `uvicorn --reload` is the usual cause.
            logger.error("running on %s: shell tools will not work. Start the backend "
                         "with `atlas start`, or uvicorn WITHOUT --reload.",
                         type(loop).__name__)
        yield
        for run in list(state.runs._runs.values()):  # noqa: SLF001
            if run.task and not run.task.done():
                state.runs.cancel(run.id)
        state.close()

    app = FastAPI(title="Atlas", lifespan=lifespan)
    app.state.atlas = state
    api = APIRouter(prefix="/api")

    # ------------------------------------------------------------- health --

    @api.get("/health")
    async def health() -> dict[str, Any]:
        run = state.runs.active()
        return {"status": "ok", "active_run": _run_view(run) if run else None}

    # -------------------------------------------------------------- chats --

    @api.get("/chats")
    async def list_chats() -> list[dict[str, Any]]:
        return state.store.list_chats()

    @api.post("/chats")
    async def create_chat(body: CreateChat | None = None) -> dict[str, Any]:
        return state.store.create_chat((body.title if body else "") or "")

    @api.get("/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        return state.view(chat_id)

    @api.patch("/chats/{chat_id}")
    async def rename_chat(chat_id: str, body: RenameChat) -> dict[str, Any]:
        state.require_chat(chat_id)
        state.store.set_title(chat_id, body.title.strip()[:200])
        return state.store.get_chat(chat_id)  # type: ignore[return-value]

    @api.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        state.require_chat(chat_id)
        if state.runs.active_for_chat(chat_id):
            raise HTTPException(409, "cannot delete a chat with an active run")
        state.store.delete_chat(chat_id)
        await SessionManager(state.settings, chat_id).delete_all()
        shutil.rmtree(paths.chat_dir(state.settings, chat_id), ignore_errors=True)
        return {"deleted": chat_id}

    # --------------------------------------------------------------- files --

    @api.post("/chats/{chat_id}/files")
    async def upload(chat_id: str, request: Request) -> dict[str, Any]:
        state.require_chat(chat_id)
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None or isinstance(upload_file, str):
            raise HTTPException(422, "no file part")
        name = Path(upload_file.filename or "upload.bin").name
        target = state.chat_dir(chat_id) / name

        # Nothing is parsed at upload: the file is saved and the model reads it
        # on demand through a skill. Copying is still blocking I/O, so it runs
        # off the event loop and cannot freeze an active run's stream.
        def _save() -> None:
            with target.open("wb") as fh:
                shutil.copyfileobj(upload_file.file, fh)

        await asyncio.to_thread(_save)
        return {"name": name, "path": str(target), "size": target.stat().st_size,
                "type": mimetypes.guess_type(name)[0] or "application/octet-stream"}

    @api.get("/chats/{chat_id}/files/{name}")
    async def download(chat_id: str, name: str) -> FileResponse:
        state.require_chat(chat_id)
        root = paths.chat_dir(state.settings, chat_id).resolve()
        target = (root / Path(name).name).resolve()
        if root not in target.parents:
            raise HTTPException(400, "path escapes the chat directory")
        if not target.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(target)

    # -------------------------------------------------------------- turns --

    @api.post("/chats/{chat_id}/messages")
    async def send(chat_id: str, body: SendMessage) -> dict[str, Any]:
        state.require_chat(chat_id)
        if not body.text.strip() and not body.files:
            raise HTTPException(422, "empty message")
        # Checked before inserting, so a 409 never leaves a stranded turn.
        state.ensure_run_slot()

        leaf = state.store.leaf(chat_id)
        if leaf is not None and leaf["status"] != COMPLETED:
            raise HTTPException(409, "the last answer did not complete: retry or edit it first")
        turn = state.store.insert_turn(
            chat_id, body.text, parent_turn_id=leaf["id"] if leaf else None,
            before_snap=leaf["after_snap"] if leaf else None, files=body.files,
        )
        if first_words := " ".join(body.text.split())[:60]:
            state.store.set_title(chat_id, first_words, only_if_empty=True)
        run = state.launch(turn, thinking=state.thinking(body.thinking))
        return {"run": _run_view(run), "chat": state.view(chat_id)}

    @api.post("/turns/{turn_id}/retry")
    async def retry(turn_id: str, body: RetryTurn | None = None) -> dict[str, Any]:
        turn = state.require_turn(turn_id)
        if turn["status"] == RUNNING:
            raise HTTPException(409, "that turn is still running")
        if not state.store.is_leaf(turn_id):
            raise HTTPException(409, "only the last answer can be retried; edit earlier turns")
        state.ensure_run_slot()

        # Newest first: the version the user just rejected is the one most
        # worth steering away from.
        previous = [answer_of(json.loads(v["render_json"] or "[]"))
                    for v in reversed(state.store.siblings_of(turn_id))]
        new = state.store.insert_turn(
            turn["chat_id"], turn["user_text"], parent_turn_id=turn["parent_turn_id"],
            before_snap=turn["before_snap"], files=json.loads(turn["files_json"] or "[]"),
        )
        run = state.launch(new, thinking=state.thinking(body.thinking if body else None),
                           retry=RetryPlan(previous=[p for p in previous if p.strip()]))
        return {"run": _run_view(run), "chat": state.view(turn["chat_id"])}

    @api.post("/turns/{turn_id}/edit")
    async def edit(turn_id: str, body: EditTurn) -> dict[str, Any]:
        turn = state.require_turn(turn_id)
        files = body.files if body.files is not None else json.loads(turn["files_json"] or "[]")
        if not body.text.strip() and not files:
            raise HTTPException(422, "empty message")
        state.ensure_run_slot()

        # Destructive by design: the old future answered a question that is
        # no longer being asked.
        try:
            old, snaps = state.store.cut_from(turn_id)
        except TreeError as exc:
            raise HTTPException(404, str(exc)) from exc
        await SessionManager(state.settings, old["chat_id"]).delete_snapshots(snaps)
        new = state.store.insert_turn(
            old["chat_id"], body.text, parent_turn_id=old["parent_turn_id"],
            before_snap=old["before_snap"], files=files,
        )
        run = state.launch(new, thinking=state.thinking(body.thinking))
        return {"run": _run_view(run), "chat": state.view(old["chat_id"])}

    @api.post("/turns/{turn_id}/select")
    async def select(turn_id: str, body: SelectTurn) -> dict[str, Any]:
        """`<` / `>`: pick another version. One query, no snapshot read."""
        turn = state.require_turn(turn_id)
        if state.runs.active_for_chat(turn["chat_id"]):
            raise HTTPException(409, "wait for the current answer to finish")
        versions = state.store.siblings_of(turn_id)
        ids = [v["id"] for v in versions]
        index = max(0, min(ids.index(turn_id) + body.delta, len(ids) - 1))
        state.store.select(ids[index])
        return state.view(turn["chat_id"])

    # --------------------------------------------------------------- runs --

    @api.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        return {**_run_view(run), "error": run.error, "events": len(run.events)}

    @api.get("/runs/{run_id}/events")
    async def run_events(run_id: str, after: int = 0) -> StreamingResponse:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")

        async def sse() -> Any:
            # Replay then follow, so a reloaded client resumes with no gaps and
            # no duplicates. `after` is the first seq the client has NOT seen.
            async for event in state.runs.stream(run, after):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @api.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        state.runs.cancel(run_id)
        return _run_view(run)

    # ------------------------------------------------------------ settings --

    def settings_view() -> dict[str, Any]:
        on_disk = json.loads(state.settings_path.read_text(encoding="utf-8"))
        return {
            "values": flatten(parse_settings(on_disk).model_dump(mode="json")),
            "tiers": {k: t.value for k, t in TIERS.items()},
            "pending_restart": changed_restart_keys(on_disk, _launched_restart_values(state)),
            "tools": ToolManager(state.settings).describe(),
            "memory": MemoryManager(state.settings).describe(),
            "skills": SkillManager(state.settings).catalogue(),
            "paths": {"root": str(paths.ROOT), "data": str(paths.data_dir(state.settings))},
        }

    @api.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return settings_view()

    @api.put("/settings")
    async def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        """Write any key. LIVE keys apply on the next turn; RESTART keys are
        saved to settings.json and take effect at the next `atlas start`."""
        unknown = sorted(k for k in patch if k not in TIERS)
        if unknown:
            raise HTTPException(422, f"unknown setting(s): {unknown}")
        on_disk = json.loads(state.settings_path.read_text(encoding="utf-8"))
        for dotted, value in patch.items():
            set_path(on_disk, dotted, value)
        try:
            write_settings(state.settings_path, on_disk)
        except SettingsError as exc:
            raise HTTPException(422, str(exc)) from exc
        state.settings = _live_settings(on_disk, state.boot)
        return settings_view()

    app.state.settings_view = settings_view
    app.include_router(api)

    # Phase 2 routes (skills, MCP) register onto the same router prefix.
    from server.extensions import register as register_extensions  # noqa: PLC0415

    register_extensions(app, state)
    return app


# ---------------------------------------------------------------- helpers --


def _live_settings(on_disk: dict[str, Any], boot: Settings) -> Settings:
    """The file's LIVE values, with RESTART values held at what the process started with."""
    merged = json.loads(json.dumps(on_disk))
    for key, value in restart_tier_values(boot.model_dump(mode="json")).items():
        set_path(merged, key, value)
    return parse_settings(merged)


def _launched_restart_values(state: Atlas) -> dict[str, Any]:
    """What the running servers were started with.

    launched.json when the CLI wrote one (its `restart_settings` block is flat,
    `{"model.path": ...}`), otherwise this process's own start-up values.
    """
    launched = paths.ROOT / "launched.json"
    if launched.is_file():
        try:
            flat = json.loads(launched.read_text(encoding="utf-8")).get("restart_settings")
            if isinstance(flat, dict) and flat:
                return flat
        except (OSError, json.JSONDecodeError):
            pass
    return restart_tier_values(state.boot.model_dump(mode="json"))


def _turn_view(turn: dict[str, Any], versions: list[str]) -> dict[str, Any]:
    return {
        "id": turn["id"],
        "parent_id": turn["parent_turn_id"],
        "user_text": turn["user_text"],
        "files": json.loads(turn["files_json"] or "[]"),
        "status": turn["status"],
        "created_at": turn["created_at"],
        "render": json.loads(turn["render_json"]) if turn["render_json"] else [],
        "stats": json.loads(turn["stats_json"]) if turn["stats_json"] else None,
        "error": turn["error"],
        "version": versions.index(turn["id"]) if turn["id"] in versions else 0,
        "versions": versions,
    }


def _run_view(run: Run) -> dict[str, Any]:
    return {"id": run.id, "chat_id": run.chat_id, "turn_id": run.turn_id, "status": run.status}


def _agent_text(user_text: str, files: list[dict[str, Any]]) -> str:
    """What the agent is told, as opposed to what the user typed.

    Nothing is parsed at upload, but a file the model has never heard of is a
    file it will not look for. So attachments are named explicitly, as
    absolute paths. Built here rather than stored, so the stored `user_text`
    stays exactly what was typed -- which is what the transcript shows and what
    a retry replays.
    """
    listed = "\n".join(
        f"- {f.get('name')} at {f.get('path')} ({f.get('size', 0)} bytes)"
        for f in files if isinstance(f, dict) and f.get("path")
    )
    if not listed:
        return user_text
    return (f"{user_text}\n\nFiles attached to this message. Read them with the matching "
            f"skill; their exact paths are below, so use them verbatim:\n{listed}").strip()


def _strip_hint(messages: list[dict[str, Any]], start: int, hint: str) -> None:
    """Remove a retry hint from the user message before the snapshot is saved.

    The hint is for this one attempt. Left in history it would be re-read on
    every later turn and tell the model to "answer differently" forever.
    """
    if start >= len(messages):
        return
    for block in messages[start].get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            block["text"] = block["text"].replace(f"\n\n{hint}", "")


__all__ = ["Atlas", "create_app"]
