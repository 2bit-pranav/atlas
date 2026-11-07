"""The backend's state (`Atlas`): settings, the chat store, runs, MCP; and the run
body: building the agent, streaming it, recording the turn."""


from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent.config import paths
from agent.config.settings import (
    load_settings,
)
from agent.integrations.mcp.pool import McpManager
from agent.model import server as llama
from agent.model.sampling import RetryPlan
from agent.platform.winpaths import model_path
from agent.prompt.notes import clock_note, retry_hint
from agent.prompt.page import page_note
from agent.runtime.factory import build_agent
from agent.store.chats import CANCELLED, COMPLETED, FAILED, ChatStore
from agent.store.snapshots import SessionManager
from agent.tools.page import page_tools
from server.events import _aiter, translate
from server.runs import Run, RunConflict, RunManager
from server.schemas import Page
from server.services.prompt import (
    _agent_text,
    _link_guidance,
    _media_blocks,
    _media_kind,
    _mention_guidance,
    _strip_hint,
)
from server.services.workspace import _changed, _scan
from server.views import _run_view, _turn_view

logger = logging.getLogger(__name__)


class Atlas:
    """The backend's state, held outside the app for testability."""

    def __init__(self, settings_path: Path) -> None:
        self.settings_path = Path(settings_path)
        # Restart tier keys keep their values for the life of the process even after settings.json changes
        self.boot = load_settings(self.settings_path)
        self.settings = self.boot
        self.store = ChatStore(paths.database(self.settings))
        self.runs = RunManager()
        # Mcp connections are per-process, not per-turn
        self.mcp = McpManager(self.settings)
        self._modalities: dict[str, bool] | None = None
        # "Allow for this chat" answers, per chat. In memory: a restart asks again.
        self.chat_grants: dict[str, list] = {}
        if n := self.store.mark_interrupted():
            logger.info("%d turn(s) left running by a previous process are now interrupted", n)
        logger.info("backend ready (root=%s, db=%s)", paths.ROOT, self.store.db_path)

    def modalities(self) -> dict[str, bool]:
        """What the loaded model can take in (vision, audio), from llama-server.

        Asked once and remembered: it changes only with the model, which needs
        a restart, and a restart starts a new backend. Not remembered while
        llama-server is still loading.
        """
        if self._modalities is None:
            try:
                import httpx

                response = httpx.get(f"http://127.0.0.1:{self.boot.ports.llama}/props", timeout=2,
                                     headers=llama.auth_headers())
                modalities = response.json().get("modalities") if response.status_code == 200 else None
            except Exception:  # noqa: BLE001 - not up yet: ask again next time
                return {}
            # The backend starts beside the model: while it loads, /props answers
            # 503 with no modalities. Remembering that hid the mic for the whole run.
            if not isinstance(modalities, dict):
                return {}
            self._modalities = {k: bool(v) for k, v in modalities.items()}
        return self._modalities

    def close(self) -> None:
        self.mcp.stop_all()
        self.store.close()

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


    def launch(
        self, turn: dict[str, Any], *, thinking: bool, retry: RetryPlan | None = None,
        page: Page | None = None,
    ) -> Run:
        try:
            run = self.runs.start(turn["chat_id"], turn["id"],
                                  context_size=self.settings.model.context_size)
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        run.page = page.model_dump() if page else None
        # Outside content read in an earlier turn is still in the history.
        run.tainted = self.store.is_tainted(turn["chat_id"])
        run.task = asyncio.create_task(self.execute(run, turn, thinking=thinking, retry=retry))
        return run

    def _page_tools(self, run: Run) -> list[Any]:
        """The page tools, for a turn sent from the side panel with its tab attached."""
        if not run.page:
            return []

        workspace = self.chat_dir(run.chat_id)
        return page_tools(run.client_call, workspace, lambda p: model_path(str(p)),
                          on_read=lambda: self.taint(run))

    def taint(self, run: Run) -> None:
        """Outside content entered this run: ask before risky tools, now and in
        every later turn of the chat (the content stays in its history)."""
        if not run.tainted:
            run.emit({"type": "tainted"})   # the UI says so from now on
        run.tainted = True
        self.store.mark_tainted(run.chat_id)

    async def execute(
        self, run: Run, turn: dict[str, Any], *, thinking: bool, retry: RetryPlan | None,
    ) -> None:
        """The run body. One task per run; the frontend is not involved."""
        # Everything that can fail is inside the `try`, preparing the prompt
        # included: an exception before it once left the run holding the only
        # slot, and every later message got 409 until a restart.
        try:
            settings = self.settings
            files = json.loads(turn["files_json"] or "[]")
            # A passage selected in the preview names its file relative to the
            # workspace; the model is given the full path, ready for edit_document.
            workspace = self.chat_dir(run.chat_id)
            refs = [{**r, "path": r.get("path") or str(workspace / str(r.get("file", "")))}
                    for r in json.loads(turn.get("refs_json") or "[]") if isinstance(r, dict)]
            media = [f for f in files if _media_kind(f) and Path(str(f.get("path", ""))).is_file()]
            text = _agent_text(turn["user_text"], files, refs, workspace=workspace)
            if guidance := _mention_guidance(turn["user_text"], settings, self.mcp, workspace):
                text = f"{text}\n\n{guidance}".strip()
            if links := _link_guidance(turn["user_text"], settings):
                text = f"{text}\n\n{links}".strip()
            if run.page:
                text = f"{text}\n\n{page_note(run.page)}".strip()
            # Only the model sees this; the chat shows the user's own text.
            text = f"{text}\n\n{clock_note()}".strip()
            hint = retry_hint(settings, retry) if retry else ""
            sm = SessionManager(settings, run.chat_id)
            # Recorded per turn, so each version shows the model that wrote it.
            run.transcript.stats["model"] = settings.model.name
            # What the workspace held before the run, so the files this turn
            # created or changed can be offered as downloads afterwards.
            run.workspace_before = _scan(self.chat_dir(run.chat_id))
            manager = sm.manager()
            # Building restores a snapshot from disk: blocking work that would
            # stall every open SSE stream if it ran on the event loop.
            agent = await asyncio.to_thread(
                build_agent, settings, chat_id=run.chat_id, thinking=thinking,
                restore_snapshot_id=turn["before_snap"], session_manager=manager,
                retry=retry, observer=run.observe, tools=self.mcp.agent_tools() + self._page_tools(run),
                approver=lambda kind, detail: run.request_approval(
                    kind, detail, settings.approvals.timeout),
                sensitive=lambda name: name in settings.tools.ask or self.mcp.is_sensitive(name),
                chat_grants=self.chat_grants.setdefault(run.chat_id, []),
                tainted=lambda: run.tainted,
                untrusted=self.mcp.is_untrusted,
                on_taint=lambda: self.taint(run),
            )
            run.agent = agent
            if run.cancel.is_set():
                raise asyncio.CancelledError
            run.emit({"type": "run_started", "chat_id": run.chat_id, "turn_id": run.turn_id})

            start = len(agent.messages)
            prompt_text = f"{text}\n\n{hint}" if hint else text
            # Images and recordings go to the model as content, after the text
            # and in separate blocks (a combined block silently drops the text).
            prompt: Any = prompt_text
            if media:
                blocks = await asyncio.to_thread(_media_blocks, media)
                prompt = ([{"text": prompt_text}] if prompt_text else []) + blocks
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
            stats["files"] = _changed(run.workspace_before,
                                      _scan(self.chat_dir(run.chat_id)))
        except OSError:
            logger.warning("could not scan the workspace of chat %s", run.chat_id, exc_info=True)
        try:
            self.store.finish_turn(run.turn_id, status, after_snap=after_snap,
                                   render=run.transcript.parts, stats=stats, error=error)
            self.store.touch(run.chat_id)
            title = (self.store.get_chat(run.chat_id) or {}).get("title") or "untitled"
            logger.info("run %s %s · chat “%s” · %s model calls · %.1fs", run.id[:4], status,
                        title, stats.get("model_calls", 0), (stats.get("duration_ms") or 0) / 1000)
        except Exception:  # noqa: BLE001 - the turn may have been cut by an edit
            logger.exception("could not record the end of turn %s", run.turn_id)
        run.finish(status, error)


__all__ = ["Atlas"]
