"""The HTTP API (design.md L4). Chats, turns, runs, settings.

One active run at a time, a run that outlives the frontend, and a chat tree
where nothing is ever deleted.

The chat tree is the interesting part and it is small, because Strands owns the
messages. What lives here is shape, status and timestamps:

    send    insert a turn with before_snap = the parent's after_snap
    retry   a sibling of the same parent, restoring the same before_snap
    edit    a sibling of the same parent, restoring the same before_snap
    <  />   move among a turn's versions and restore that version's after_snap
    cancel  agent.cancel(), then restore before_snap so no half-finished tool
            call survives into the next turn

A retry or an edit reuses the parent's restore point, so a retry replays the
same question from the same state -- which is the point of a retry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.core.agent_factory import build_agent
from agent.core.chats import (
    CANCELLED,
    ChatStore,
    COMPLETED,
    FAILED,
    INTERRUPTED,
    RUNNING,
)
from agent.core.memory_manager import MemoryManager
from agent.core.session_manager import SessionManager
from agent.core.settings import (
    Settings,
    SettingsError,
    TIERS,
    Tier,
    changed_restart_keys,
    flatten,
    load_settings,
    parse_settings,
)
from agent.core.skill_manager import SkillError, SkillManager
from agent.core.tool_manager import ToolManager
from server.events import _aiter, translate
from server.runs import Run, RunConflict, RunManager

logger = logging.getLogger(__name__)

TERMINAL = {COMPLETED, FAILED, CANCELLED, INTERRUPTAL := INTERRUPTED}


# ----------------------------------------------------------------- models --


class CreateChat(BaseModel):
    title: str = ""


class SendMessage(BaseModel):
    text: str = ""
    files: list[dict[str, Any]] = Field(default_factory=list)
    thinking: bool | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class EditTurn(BaseModel):
    text: str


# ------------------------------------------------------------------ app ----


class Atlas:
    """The backend's state, held outside the app for testability."""

    def __init__(self, settings_path: Path, root: Path) -> None:
        self.settings_path = Path(settings_path)
        self.root = Path(root)
        self._settings_lock = threading.RLock()
        self.settings = load_settings(self.settings_path)

        data_dir = self.root / self.settings.paths.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ChatStore(data_dir / "atlas.db")
        self.runs = RunManager()

        # Anything left running by a crash is retryable, not lost.
        for turn in self.store.interrupted_running_turns():
            self.store.set_status(turn["id"], INTERRUPTED)
        logger.info("backend ready (db=%s)", self.store.db_path)

    # ------------------------------------------------------------ helpers --

    def reload_settings(self) -> None:
        with self._settings_lock:
            self.settings = load_settings(self.settings_path)

    def chat_dir(self, chat_id: str) -> Path:
        path = self.root / self.settings.paths.data_dir / "chats" / chat_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def session_manager(self, chat_id: str) -> SessionManager:
        return SessionManager(self.settings, chat_id)

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

    # -------------------------------------------------------------- runs --

    async def execute(
        self, run: Run, *, user_text: str, restore: str | None, thinking: bool
    ) -> None:
        """The run body. One task per run; the frontend is not involved."""
        turn_id = run.turn_id
        try:
            sm = self.session_manager(run.chat_id)
            manager = sm.manager()
            agent = build_agent(
                self.settings,
                chat_id=run.chat_id,
                thinking=thinking,
                restore_snapshot_id=restore,
                session_manager=manager,
                extra_instructions=self.settings.regeneration.instructions,
            )
            run.agent = agent

            if run.cancel.is_set():
                raise asyncio.CancelledError

            run.emit({"type": "run_started", "chat_id": run.chat_id, "turn_id": turn_id})

            async def stream():
                # The translator is created ONCE for the run, not per event.
                # It keeps a toolUseId -> name map so a bare toolResult can be
                # attributed to the tool that produced it; a fresh translator
                # per event throws that map away and every tool_end reports
                # name="?". It is also an ASYNC generator, so the source has to
                # be iterated in one pass -- calling translate() per event does
                # not even typecheck.
                async for out in translate(_aiter(agent.stream_async(user_text))):
                    if run.cancel.is_set():
                        raise asyncio.CancelledError
                    run.emit(out)

            await stream()

            snap = await manager.save_snapshot(agent, is_latest=False)
            self.store.set_status(turn_id, COMPLETED, after_snap=snap)
            run.finish(COMPLETED)

        except (asyncio.CancelledError, KeyboardInterrupt):
            # Restore the pre-turn state so no half-finished tool call is left
            # in the history the next turn builds on.
            try:
                sm = self.session_manager(run.chat_id)
                manager = sm.manager()
                agent = build_agent(
                    self.settings, chat_id=run.chat_id,
                    restore_snapshot_id=self.store.get_turn(turn_id)["before_snap"],
                    session_manager=manager,
                )
                await manager.save_snapshot(agent, is_latest=False)
            except Exception:  # noqa: BLE001
                logger.exception("cancel rollback failed")
            self.store.set_status(turn_id, CANCELLED)
            run.finish(CANCELLED)

        except Exception as exc:  # noqa: BLE001
            logger.exception("run %s failed", run.id)
            self.store.set_status(turn_id, FAILED)
            run.finish(FAILED, f"{type(exc).__name__}: {exc}")

        finally:
            run.agent = None
            self.runs.adopt(run)

    def launch(
        self, *, chat_id: str, turn_id: str, user_text: str,
        restore: str | None, thinking: bool,
    ) -> Run:
        """Start a run. 409 if one is already active."""
        try:
            run = self.runs.start(chat_id, turn_id)
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        run.task = asyncio.create_task(
            self.execute(run, user_text=user_text, restore=restore, thinking=thinking)
        )
        return run

    def ensure_run_slot(self) -> None:
        try:
            self.runs.ensure_available()
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc


def create_app(settings_path: str | Path = "settings.json",
               root: str | Path = ".") -> FastAPI:
    app = FastAPI(title="Atlas")
    state = Atlas(Path(settings_path), Path(root))
    app.state.atlas = state

    # ------------------------------------------------------------- health --

    @app.get("/health")
    async def health() -> dict[str, Any]:
        run = state.runs.active()
        return {
            "status": "ok",
            "active_run": run.id if run else None,
            "runs_known": len(state.runs._runs),  # noqa: SLF001 - health wants the count
        }

    # -------------------------------------------------------------- chats --

    @app.post("/chats")
    async def create_chat(body: CreateChat | None = None) -> dict[str, Any]:
        return state.store.create_chat((body.title if body else "") or "")

    @app.get("/chats")
    async def list_chats() -> list[dict[str, Any]]:
        return state.store.list_chats()

    @app.get("/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        chat = state.require_chat(chat_id)
        run = state.runs.active_for_chat(chat_id)
        path = state.store.path(chat_id)
        nodes = []
        for turn in path:
            versions = state.store.siblings_of(turn["id"])
            nodes.append({
                "id": turn["id"],
                "user_text": turn["user_text"],
                "files": json.loads(turn["files_json"] or "[]"),
                "status": turn["status"],
                "created_at": turn["created_at"],
                "snapshot": turn["after_snap"],
                "version": next(
                    (i for i, v in enumerate(versions) if v["id"] == turn["id"]), 0
                ),
                "version_count": len(versions),
            })
        return {
            "id": chat["id"],
            "title": chat["title"],
            "turns": nodes,
            "active_run": run.id if run else None,
        }

    @app.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        state.require_chat(chat_id)
        if state.runs.active_for_chat(chat_id):
            raise HTTPException(409, "cannot delete a chat with an active run")
        state.store.delete_chat(chat_id)
        # The snapshot directory is deliberately left: delete_session is never
        # called anywhere in Atlas, so a stray file costs disk, not correctness.
        return {"deleted": chat_id}

    @app.get("/chats/{chat_id}/turns/{turn_id}")
    async def get_turn(chat_id: str, turn_id: str) -> dict[str, Any]:
        state.require_chat(chat_id)
        turn = state.require_turn(turn_id)
        if turn["chat_id"] != chat_id:
            raise HTTPException(404, f"no turn {turn_id} in chat {chat_id}")
        sm = state.session_manager(chat_id)
        messages: list[dict[str, Any]] = []
        if turn["after_snap"]:
            # A snapshot contains the whole conversation. Returning that whole
            # list for each visible turn made the second assistant row contain
            # the first answer again, the third row contain the first two, and
            # so on. Slice at this turn's immutable restore point instead.
            before_snap_id = turn.get("before_snap")
            if not before_snap_id and turn.get("parent_turn_id"):
                parent_turn = state.store.get_turn(turn["parent_turn_id"])
                if parent_turn and parent_turn.get("after_snap"):
                    before_snap_id = parent_turn["after_snap"]

            before_count = 0
            if before_snap_id:
                try:
                    before = build_agent(
                        state.settings,
                        chat_id=chat_id,
                        restore_snapshot_id=before_snap_id,
                        session_manager=sm.manager(),
                    )
                    before_count = len(before.messages)
                except Exception:
                    before_count = 0
            # Replay through a throwaway agent to read the stored messages.
            agent = build_agent(
                state.settings, chat_id=chat_id, restore_snapshot_id=turn["after_snap"],
                session_manager=sm.manager(),
            )
            messages = _readable(agent.messages[before_count:])
        return {"turn": turn, "messages": messages}

    # --------------------------------------------------------------- files --

    @app.post("/chats/{chat_id}/files")
    async def upload(chat_id: str, request: Request) -> dict[str, Any]:
        state.require_chat(chat_id)
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            raise HTTPException(422, "no file part")
        name = getattr(upload_file, "filename", None) or "upload.bin"
        target = state.chat_dir(chat_id) / Path(name).name
        # Nothing is parsed at upload (design.md principle 3): the file is
        # saved and the model reads it on demand through a skill.
        # Starlette has already accepted the multipart body, but copying a
        # large spooled file is still blocking filesystem I/O. Keep it out of
        # the event loop so an upload cannot freeze an active run or its SSE.
        def _save() -> None:
            with target.open("wb") as fh:
                shutil.copyfileobj(upload_file.file, fh)  # type: ignore[union-attr]

        await asyncio.to_thread(_save)
        return {
            "name": name,
            "type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "path": str(target),
            "size": target.stat().st_size,
        }

    @app.get("/chats/{chat_id}/files/{name}")
    async def download(chat_id: str, name: str) -> FileResponse:
        state.require_chat(chat_id)
        target = (state.chat_dir(chat_id) / Path(name).name).resolve()
        root = state.chat_dir(chat_id).resolve()
        if root not in target.parents:
            raise HTTPException(400, "path escapes the chat directory")
        if not target.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(target)

    # ------------------------------------------------------------- sending --

    def _thinking_for(settings: Settings, override: bool | None) -> bool:
        return settings.sampling.thinking if override is None else override

    def _agent_text(user_text: str, files: list[dict[str, Any]]) -> str:
        """What the agent is told, as opposed to what the user typed.

        design.md principle 3 is that nothing is parsed at upload: the bytes are
        saved and the model reads them through a skill. But a file the model has
        never heard of is a file it will not look for, and the observed result
        was the model explaining that it could not find a path the user had
        never given it. Uploaded files therefore have to be named explicitly, as
        absolute paths, or the document feature does nothing.

        Built here rather than in the client for two reasons: the manifest is
        part of how Atlas talks to its own model, not something every client has
        to rediscover; and the *stored* `user_text` must stay exactly what was
        typed, because that is what the transcript displays and what a retry
        replays. A retry rebuilds this from the turn's own `files`, so an
        attachment survives being asked again.
        """
        if not files:
            return user_text
        listed = "\n".join(
            f"- {f.get('name')} at {f.get('path')} ({f.get('size', 0)} bytes)"
            for f in files
            if isinstance(f, dict) and f.get("path")
        )
        if not listed:
            return user_text
        return (
            f"{user_text}\n\n"
            f"Files attached to this message. Read them with the matching "
            f"skill; their exact paths are below, so use them verbatim:\n"
            f"{listed}"
        ).strip()

    @app.post("/chats/{chat_id}/messages")
    async def send(chat_id: str, body: SendMessage) -> dict[str, Any]:
        state.require_chat(chat_id)
        if not body.text.strip() and not body.files:
            raise HTTPException(422, "empty message")

        # Check before inserting. Previously a 409 created a stranded
        # `running` turn and moved selected_child even though no task existed.
        state.ensure_run_slot()

        # A send continues from whatever is currently selected, not from the
        # turn the user was looking at when they started typing.
        leaf = state.store.leaf(chat_id)
        if leaf is not None and leaf["status"] != COMPLETED:
            raise HTTPException(
                409, "select a completed version before sending a follow-up"
            )
        parent = leaf["id"] if leaf else None
        before = leaf["after_snap"] if leaf else None

        turn = state.store.insert_turn(
            chat_id, body.text, parent_turn_id=parent,
            before_snap=before, files=body.files,
        )
        # Name the chat after its first question. The frontend creates a chat on
        # demand so that a new conversation needs no separate step, which means
        # it arrives here untitled -- and an untitled chat is a row of blank
        # entries in the sidebar, indistinguishable from each other. The guard
        # lives in the SQL, so a rename request for the first turn of an
        # already-titled chat cannot overwrite a title the user set.
        first_words = " ".join(body.text.split())[:60]
        if first_words:
            state.store.set_title(chat_id, first_words)

        run = state.launch(
            chat_id=chat_id, turn_id=turn["id"],
            user_text=_agent_text(body.text, body.files),
            restore=before, thinking=_thinking_for(state.settings, body.thinking),
        )
        return {"run_id": run.id, "turn_id": turn["id"]}

    @app.post("/turns/{turn_id}/retry")
    async def retry(turn_id: str) -> dict[str, Any]:
        turn = state.require_turn(turn_id)
        if turn["status"] == RUNNING:
            raise HTTPException(409, "that turn is still running")
        state.ensure_run_slot()
        # A retry is a sibling with the SAME restore point, so the same question
        # is asked again from the same state.
        new = state.store.insert_turn(
            turn["chat_id"], turn["user_text"], parent_turn_id=turn["parent_turn_id"],
            before_snap=turn["before_snap"], files=json.loads(turn["files_json"] or "[]"),
        )
        run = state.launch(
            chat_id=turn["chat_id"], turn_id=new["id"],
            user_text=_agent_text(turn["user_text"],
                                  json.loads(turn["files_json"] or "[]")),
            restore=turn["before_snap"],
            thinking=_thinking_for(state.settings, None),
        )
        return {"run_id": run.id, "turn_id": new["id"]}

    @app.post("/turns/{turn_id}/edit")
    async def edit(turn_id: str, body: EditTurn) -> dict[str, Any]:
        turn = state.require_turn(turn_id)
        if not body.text.strip():
            raise HTTPException(422, "empty text")
        if turn["status"] == RUNNING:
            raise HTTPException(409, "that turn is still running")
        state.ensure_run_slot()
        # Also a sibling, also the same restore point. The original version
        # stays on disk and stays selectable; nothing is discarded.
        new = state.store.insert_turn(
            turn["chat_id"], body.text, parent_turn_id=turn["parent_turn_id"],
            before_snap=turn["before_snap"], files=json.loads(turn["files_json"] or "[]"),
        )
        run = state.launch(
            chat_id=turn["chat_id"], turn_id=new["id"],
            user_text=_agent_text(body.text,
                                  json.loads(turn["files_json"] or "[]")),
            restore=turn["before_snap"],
            thinking=_thinking_for(state.settings, None),
        )
        return {"run_id": run.id, "turn_id": new["id"]}

    @app.post("/turns/{turn_id}/select")
    async def select(turn_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Move among a turn's versions with `<` / `>`."""
        turn = state.require_turn(turn_id)
        delta = int(body.get("delta", 0))
        target = state.store.walk_sibling(turn_id, delta)
        if target is None:
            raise HTTPException(404, "no such turn")
        if target["parent_turn_id"]:
            state.store.select_child(target["parent_turn_id"], target["id"])
        else:
            state.store.select_root(target["chat_id"], target["id"])
        return {
            "turn_id": target["id"],
            "snapshot": target["after_snap"],
            "versions": [v["id"] for v in state.store.siblings_of(turn_id)],
        }

    # ---------------------------------------------------------------- runs --

    @app.get("/runs/active")
    async def active_run() -> dict[str, Any]:
        run = state.runs.active()
        return {"run": None if run is None else {
            "id": run.id, "chat_id": run.chat_id, "turn_id": run.turn_id,
            "status": run.status,
        }}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        return {
            "id": run.id, "chat_id": run.chat_id, "turn_id": run.turn_id,
            "status": run.status, "error": run.error,
            "events": len(run.events),
        }

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str, after: int = 0) -> StreamingResponse:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")

        async def sse() -> Any:
            # Replay then follow, so a reloaded client resumes with no gaps
            # and no duplicates. `after` is the last seq the client saw.
            async for event in state.runs.stream(run, after):
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        state.runs.cancel(run_id)
        return {"cancelling": not run.done, "status": run.status}

    # ------------------------------------------------------------ settings --

    def _settings_view() -> dict[str, Any]:
        settings = state.settings
        raw = json.loads(settings.model_dump_json())
        leaves = flatten(raw)
        launched_path = state.root / "launched.json"
        launched = {}
        if launched_path.is_file():
            try:
                launched = json.loads(launched_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                launched = {}
        restart_changed = changed_restart_keys(raw, launched) if launched else {}
        return {
            "values": leaves,
            "tiers": {k: t.value for k, t in TIERS.items()},
            "pending_restart": restart_changed,
            "tools": ToolManager(settings).describe(),
            "memory": MemoryManager(settings).describe(),
            "skills": SkillManager(settings).catalogue(),
        }

    @app.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return _settings_view()

    @app.put("/settings")
    async def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
        """Update LIVE keys only. RESTART keys are refused, not ignored."""
        current = json.loads(state.settings.model_dump_json())

        restart_touched = {
            k for k in patch if TIERS.get(k) is Tier.RESTART
        }
        if restart_touched:
            raise HTTPException(
                409,
                f"these need a restart and cannot be changed here: "
                f"{sorted(restart_touched)}",
            )

        for dotted, value in patch.items():
            if dotted not in TIERS:
                raise HTTPException(422, f"unknown setting {dotted!r}")
            if TIERS[dotted] is not Tier.LIVE:
                raise HTTPException(409, f"{dotted} needs a restart")
            node = current
            parts = dotted.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

        try:
            state.settings = parse_settings(current)
        except SettingsError as exc:
            raise HTTPException(422, str(exc)) from exc

        # Written back so the CLI and the next process agree. Written
        # atomically: a crash mid-write would otherwise leave unparseable JSON.
        target = state.settings_path
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(target)
        state.reload_settings()
        return _settings_view()

    @app.get("/skills")
    async def list_skills() -> list[dict[str, Any]]:
        try:
            return SkillManager(state.settings).catalogue()
        except SkillError as exc:
            raise HTTPException(500, str(exc)) from exc

    return app


def _readable(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip a Strands message list down to what a client needs to render."""
    out: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, dict):
            content = [content]
        for block in content or []:
            if not isinstance(block, dict):
                continue
            if "text" in block:
                out.append({"role": message.get("role"), "kind": "text",
                            "text": block["text"]})
            elif "toolUse" in block:
                out.append({"role": "assistant", "kind": "tool_use",
                            "name": block["toolUse"].get("name"),
                            "input": block["toolUse"].get("input")})
            elif "toolResult" in block:
                result = block["toolResult"]
                out.append({"role": "user", "kind": "tool_result",
                            "status": result.get("status"),
                            "text": _flatten(result.get("content"))})
    return out


def _flatten(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict)
        )
    return str(content or "")


app = None  # built by the CLI, which knows the settings path


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
