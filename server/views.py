"""What the API returns for a turn and for a run."""


from __future__ import annotations

import json
from typing import Any

from server.runs import Run


def _turn_view(turn: dict[str, Any], versions: list[str]) -> dict[str, Any]:
    return {
        "id": turn["id"],
        "parent_id": turn["parent_turn_id"],
        "user_text": turn["user_text"],
        "files": json.loads(turn["files_json"] or "[]"),
        "refs": json.loads(turn.get("refs_json") or "[]"),
        "status": turn["status"],
        "created_at": turn["created_at"],
        "render": json.loads(turn["render_json"]) if turn["render_json"] else [],
        "stats": json.loads(turn["stats_json"]) if turn["stats_json"] else None,
        "error": turn["error"],
        "version": versions.index(turn["id"]) if turn["id"] in versions else 0,
        "versions": versions,
    }


def _run_view(run: Run) -> dict[str, Any]:
    return {"id": run.id, "chat_id": run.chat_id, "turn_id": run.turn_id, "status": run.status,
            "tokens_per_second": run.transcript.stats.get("tokens_per_second")}


__all__ = []
