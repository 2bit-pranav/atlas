"""A trace per run: everything that happened, written as it happens.

One JSON line per record in `<data>/traces/<chat>/<turn>-<run>.jsonl`, appended
and flushed one at a time, so a crash keeps what came before it:

    {"t": 1731400000.12, "type": "run", "chat", "turn", "run", "model", "thinking", ...}
    {"t": ..., "type": "model_request", "call": 1, "body": {...}}       the exact request sent
    {"t": ..., "type": "model_response", "call": 1, "text", "reasoning", "tool_calls",
                                         "finish_reason", "timings", "usage", "ms"}
    {"t": ..., "type": "model_error", "call": 1, "error"}
    {"t": ..., "type": "policy", "step", "tool", "verdict", "reason"?, "args"?, ...}
    {"t": ..., "type": "event", "event": {...}}                          every run event, as streamed
    {"t": ..., "type": "end", "status", "error"?}

It holds the whole conversation and what the pages said, like the chat itself:
it lives in the data folder (the agent can never read it), goes with its chat,
and is deleted after `KEEP_DAYS`. Never a key: request headers are not traced.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from pathlib import Path
from typing import Any

#: Traces older than this are deleted when a run starts.
KEEP_DAYS = 14


def traces_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "traces"


class Trace:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()   # the policy and the model write from the agent's threads too

    def write(self, kind: str, **data: Any) -> None:
        line = json.dumps({"t": round(time.time(), 3), "type": kind, **data}, ensure_ascii=False, default=str)
        with self._lock:
            if self._fh.closed:
                return
            with contextlib.suppress(OSError, ValueError):   # a full disk must not fail the run
                self._fh.write(line + "\n")
                self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()


def open_trace(data_dir: Path, chat_id: str, turn_id: str, run_id: str) -> Trace:
    sweep(data_dir)
    return Trace(traces_dir(data_dir) / chat_id / f"{turn_id}-{run_id}.jsonl")


def sweep(data_dir: Path, keep_days: float = KEEP_DAYS) -> None:
    """Delete traces older than `keep_days`, and folders left empty."""
    root = traces_dir(data_dir)
    if not root.is_dir():
        return
    cutoff = time.time() - keep_days * 86400
    for chat in root.iterdir():
        if not chat.is_dir():
            continue
        for f in chat.glob("*.jsonl"):
            with contextlib.suppress(OSError):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
        with contextlib.suppress(OSError):
            chat.rmdir()   # only when empty


def delete_chat(data_dir: Path, chat_id: str) -> None:
    import shutil

    shutil.rmtree(traces_dir(data_dir) / chat_id, ignore_errors=True)


def find(data_dir: Path, run: str | None = None) -> Path | None:
    """A run's trace by its id (or the start of it), or the newest one."""
    files = [f for f in traces_dir(data_dir).glob("*/*.jsonl")]
    if run:
        files = [f for f in files if f.stem.split("-", 1)[-1].startswith(run)]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def for_turn(data_dir: Path, chat_id: str, turn_id: str) -> Path | None:
    files = list((traces_dir(data_dir) / chat_id).glob(f"{turn_id}-*.jsonl"))
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def read(path: Path) -> list[dict[str, Any]]:
    """Every record; a line cut short by a crash is skipped."""
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
    return out


__all__ = ["KEEP_DAYS", "Trace", "delete_chat", "find", "for_turn", "open_trace", "read", "sweep", "traces_dir"]
