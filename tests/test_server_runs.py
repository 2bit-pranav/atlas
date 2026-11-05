"""The backend's run lifecycle (server/app.py `Atlas`):
however a run ends, its slot is freed and its turn is recorded."""

from __future__ import annotations

import asyncio

import pytest
from helpers import settings_file

from server.state import Atlas


@pytest.fixture
def atlas(tmp_path):
    path = settings_file(tmp_path)
    state = Atlas(path)
    yield state
    state.close()


def test_a_run_that_fails_before_the_model_frees_its_slot(atlas) -> None:
    """Preparing the prompt ran before the `try`, so an exception there left
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
