"""Offline tests for the backend's run lifecycle (server/app.py `Atlas`):
however a run ends, its slot is freed and its turn is recorded."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from server.app import Atlas

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def atlas(tmp_path):
    settings = json.loads((ROOT / "settings.example.json").read_text(encoding="utf-8"))
    settings["paths"] = {"data_dir": str(tmp_path / "data")}
    settings["mcp"]["config"] = str(tmp_path / "mcp.json")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    state = Atlas(path)
    yield state
    state.close()


def test_a_run_that_fails_before_the_model_frees_its_slot(atlas) -> None:
    """B3: preparing the prompt ran before the `try`, so an exception there left
    the run active forever: every later message got 409 until a restart."""
    chat = atlas.store.create_chat()["id"]
    turn = atlas.store.insert_turn(chat, "hello", parent_turn_id=None, before_snap=None)
    turn = {**turn, "files_json": "{not json"}            # anything that throws while preparing

    async def scenario() -> None:
        run = atlas.runs.start(chat, turn["id"])
        await atlas.execute(run, turn, thinking=False, retry=None)

    asyncio.run(scenario())
    assert atlas.runs.active() is None                    # the next message can start
    assert atlas.store.get_turn(turn["id"])["status"] == "failed"
