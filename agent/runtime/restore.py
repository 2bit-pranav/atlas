"""Restoring an agent from a Strands snapshot, and re-setting its prompt afterwards."""

from __future__ import annotations

from typing import Any

from strands_harness import build_system_prompt


def _restore(
    agent: Any, session_manager: Any, snapshot_id: str, instructions: str
) -> None:
    """Restore a snapshot, then re-apply what the snapshot may have overridden.

    The snapshot's stored `system_prompt` wins over the one passed to
    `create_harness`, so the prompt is set again afterwards. Without this, an
    edited prompt would have no effect on any chat that already has history.

    The prompt is **recomposed** with `build_system_prompt`, the harness's own
    function: assigning our text raw dropped the harness guidance, leaving only
    our text on the first restored turn.
    """
    async def _do() -> bool:
        return await session_manager.restore_snapshot(
            agent, snapshot_id=snapshot_id
        )

    ok = _run(_do())
    if not ok:
        raise ValueError(
            f"restore_snapshot({snapshot_id}) failed. The id is unknown, or the "
            "snapshot file was pruned. Retrying is not possible; the chat tree "
            "points at a snapshot that does not exist."
        )
    agent.system_prompt = _harness_prompt(instructions)


def _harness_prompt(instructions: str) -> str:
    """The harness prompt with our instructions appended, as the harness would.

    Returns an empty string when there is nothing to append, which leaves the
    agent on the harness default.
    """
    if not instructions or not instructions.strip():
        return ""
    return str(build_system_prompt(instructions=instructions))


def _run(coro: Any) -> Any:
    """Run a coroutine from sync code, whether or not a loop is already running."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Called on a thread with a running loop: run in a private loop on another
    # thread. The server calls `build_agent` via `asyncio.to_thread`, so it
    # normally takes the `asyncio.run` path above.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = []
