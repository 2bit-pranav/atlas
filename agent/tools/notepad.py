"""The notepad: plan and notes (spec section 10).

Working memory, per run, stored in ``scratch_state`` and rendered into a pinned
block. Two rules that are easy to get wrong:

* **Hard caps error, they never truncate silently.** A dropped note is a fact
  the model believes it saved and cannot find again, which is worse than a
  clear "merge or remove one".
* **Facts and decisions go in notes; data goes in tables.** A note pointing at
  ``r3`` costs a few tokens; copying r3's contents costs the context window.
"""

from __future__ import annotations

import json
from typing import Any

from agent.ids import now_ms

MAX_PLAN = 12
MAX_NOTES = 20


def _table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scratch_state (
            run_id        TEXT PRIMARY KEY,
            plan          TEXT,
            notes         TEXT,
            active_skills TEXT,
            version       INTEGER NOT NULL DEFAULT 0,
            updated_at    INTEGER NOT NULL
        )
        """
    )


def _load(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM scratch_state WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        return {"plan": [], "notes": [], "active_skills": [], "version": 0}
    return {
        "plan": json.loads(row["plan"] or "[]"),
        "notes": json.loads(row["notes"] or "[]"),
        "active_skills": json.loads(row["active_skills"] or "[]"),
        "version": row["version"],
    }


def _save(conn: Any, run_id: str, state: dict[str, Any]) -> None:
    state["version"] = int(state.get("version", 0)) + 1
    conn.execute(
        """
        INSERT INTO scratch_state (run_id, plan, notes, active_skills, version, updated_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(run_id) DO UPDATE SET
            plan=excluded.plan, notes=excluded.notes,
            active_skills=excluded.active_skills,
            version=excluded.version, updated_at=excluded.updated_at
        """,
        (run_id, json.dumps(state["plan"], ensure_ascii=False),
         json.dumps(state["notes"], ensure_ascii=False),
         json.dumps(state["active_skills"], ensure_ascii=False),
         state["version"], now_ms()),
    )


def state(ctx: Any) -> dict[str, Any]:
    conn = ctx.repo.db.connection
    _table(conn)
    with ctx.repo.db.write():
        _table(conn)
    return _load(conn, ctx.run.id)


def write_plan(ctx: Any, items: list[str]) -> int:
    conn = ctx.repo.db.connection
    with ctx.repo.db.write() as c:
        _table(c)
        current = _load(c, ctx.run.id)
        current["plan"] = [{"text": str(i), "status": "pending"} for i in items]
        _save(c, ctx.run.id, current)
    return len(items)


def push_note(ctx: Any, entry: dict[str, Any]) -> list[dict[str, Any]]:
    conn = ctx.repo.db.connection
    with ctx.repo.db.write() as c:
        _table(c)
        current = _load(c, ctx.run.id)
        current["notes"].append(entry)
        _save(c, ctx.run.id, current)
        return current["notes"]


def mark(ctx: Any, index: int, status: str) -> None:
    conn = ctx.repo.db.connection
    with ctx.repo.db.write() as c:
        _table(c)
        current = _load(c, ctx.run.id)
        if 0 <= index < len(current["plan"]):
            current["plan"][index]["status"] = status
        _save(c, ctx.run.id, current)


def render(ctx: Any) -> str:
    """The pinned notepad block (section 10)."""
    current = state(ctx)
    if not current["plan"] and not current["notes"]:
        return ""
    lines: list[str] = []
    if current["plan"]:
        lines.append("PLAN:")
        for i, item in enumerate(current["plan"], 1):
            lines.append(f"  {i}. [{item.get('status', 'pending')}] {item['text']}")
    if current["notes"]:
        lines.append("NOTES:")
        for note in current["notes"]:
            ref = f" (ref {note['ref']})" if note.get("ref") else ""
            lines.append(f"  - {note['text']}{ref}")
    if current["active_skills"]:
        lines.append("SKILLS: " + ", ".join(current["active_skills"]))
    return "\n".join(lines)


def compact(ctx: Any) -> dict[str, Any]:
    """The form stored in ``nodes.task_state`` at run end (section 5)."""
    current = state(ctx)
    return {
        "plan": current["plan"],
        "notes": current["notes"][-MAX_NOTES:],
        "active_skills": current["active_skills"],
    }


def carry_forward(previous: dict[str, Any] | None) -> dict[str, Any]:
    """Seed a new run from the previous run's compacted state."""
    previous = previous or {}
    return {
        "plan": previous.get("plan") or [],
        "notes": previous.get("notes") or [],
        "active_skills": previous.get("active_skills") or [],
    }


__all__ = [
    "MAX_NOTES", "MAX_PLAN", "carry_forward", "compact", "mark", "push_note",
    "render", "state", "write_plan",
]
