"""Turns: send a message, retry the last answer, edit any message, switch versions."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from agent.model.sampling import RetryPlan
from agent.store.chats import COMPLETED, RUNNING, TreeError
from agent.store.snapshots import SessionManager
from server.schemas import (
    EditTurn,
    RetryTurn,
    SelectTurn,
    SendMessage,
)
from server.transcript import answer_of
from server.views import _run_view


def register(api: Any, state: Any) -> None:
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
            before_snap=leaf["after_snap"] if leaf else None, files=body.files, refs=body.refs,
        )
        if first_words := " ".join(body.text.split())[:60]:
            state.store.set_title(chat_id, first_words, only_if_empty=True)
        run = state.launch(turn, thinking=state.thinking(body.thinking), page=body.page)
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
            refs=json.loads(turn.get("refs_json") or "[]"),
        )
        run = state.launch(new, thinking=state.thinking(body.thinking if body else None),
                           retry=RetryPlan(previous=[p for p in previous if p.strip()]),
                           page=body.page if body else None)
        return {"run": _run_view(run), "chat": state.view(turn["chat_id"])}

    @api.post("/turns/{turn_id}/edit")
    async def edit(turn_id: str, body: EditTurn) -> dict[str, Any]:
        turn = state.require_turn(turn_id)
        files = body.files if body.files is not None else json.loads(turn["files_json"] or "[]")
        refs = body.refs if body.refs is not None else json.loads(turn.get("refs_json") or "[]")
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
        # Files in the workspace are never touched by an edit: documents the
        # agent made or changed for the deleted turns stay, and stay listed.
        new = state.store.insert_turn(
            old["chat_id"], body.text, parent_turn_id=old["parent_turn_id"],
            before_snap=old["before_snap"], files=files, refs=refs,
        )
        run = state.launch(new, thinking=state.thinking(body.thinking), page=body.page)
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
