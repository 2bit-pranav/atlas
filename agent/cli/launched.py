"""`launched.json`, ports, and stopping what Atlas started.

`launched.json` records the running launch: each process with its start time
(so a reused PID is never mistaken for ours), the URLs, and the restart-tier
settings it was started with. The backend compares those with settings.json
to say which saved settings wait for a restart. It is deleted on a clean stop.

The model files are fingerprinted by size and modification time, not hashed:
hashing the 2.6 GB GGUF took 2.6 s on every start and nothing read the hash.
"""


from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.common.ids import new_ulid
from agent.config.settings import changed_restart_keys, restart_tier_values

IS_WINDOWS = sys.platform == "win32"


@dataclass
class LaunchedInfo:
    launch_id: str
    started_at: int
    mode: str = "normal"
    processes: dict[str, Any] = field(default_factory=dict)
    urls: dict[str, str] = field(default_factory=dict)
    restart_settings: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] | None = None

    @classmethod
    def new(cls, mode: str) -> LaunchedInfo:
        return cls(launch_id=new_ulid(), started_at=int(time.time() * 1000), mode=mode)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LaunchedInfo:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def fingerprint(path: str | Path | None) -> dict[str, Any] | None:
    if not path or not Path(path).exists():
        return None
    stat = Path(path).stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def process_entry(pid: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"pid": pid, "create_time": None, "cmdline": None}
    with contextlib.suppress(Exception):
        import psutil

        proc = psutil.Process(pid)
        entry["create_time"] = proc.create_time()
        entry["cmdline"] = " ".join(proc.cmdline()[:4])
    return entry


def is_alive(entry: dict[str, Any]) -> bool:
    """The recorded process still runs, and is the same process (not a reused PID)."""
    try:
        import psutil

        proc = psutil.Process(int(entry["pid"]))
        started = entry.get("create_time")
        if started is not None and abs(proc.create_time() - float(started)) > 2.0:
            return False
        return proc.is_running()
    except Exception:  # noqa: BLE001
        return False


def write_launched(path: Path, info: LaunchedInfo, settings_dict: dict[str, Any]) -> None:
    info.restart_settings = restart_tier_values(settings_dict)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(info.to_json(), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_launched(path: Path) -> LaunchedInfo | None:
    try:
        return LaunchedInfo.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def running(info: LaunchedInfo | None) -> dict[str, dict[str, Any]]:
    """The recorded processes that are still alive."""
    if info is None:
        return {}
    return {name: e for name, e in info.processes.items() if is_alive(e)}


def restart_required(settings_dict: dict[str, Any], launched: LaunchedInfo | None) -> dict[str, Any]:
    if launched is None:
        return restart_tier_values(settings_dict)
    return changed_restart_keys(settings_dict, launched.restart_settings)


__all__ = ["IS_WINDOWS", "LaunchedInfo", "fingerprint", "is_alive", "load_launched", "process_entry", "restart_required", "running", "write_launched"]
