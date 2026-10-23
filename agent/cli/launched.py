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
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from agent.cli.processes import kill_pid_tree
from agent.core.ids import new_ulid
from agent.core.settings import changed_restart_keys, restart_tier_values

IS_WINDOWS = sys.platform == "win32"
#: What each service's process looks like; a port holder that does not match
#: its service is someone else's program and is left alone.
OURS = {"llama": ("llama",), "backend": ("uvicorn", "server.main"), "web": ("vite", "node", "npm")}


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


# --------------------------------------------------------------------- ports --


def find_pids_by_port(port: int) -> list[int]:
    """PIDs listening on `port`."""
    pids: set[int] = set()
    with contextlib.suppress(Exception):
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port and conn.pid:
                pids.add(conn.pid)
    if pids:
        return sorted(pids)
    # psutil can be denied the table; netstat and lsof are not.
    with contextlib.suppress(Exception):
        if IS_WINDOWS:
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=5).stdout
            for parts in (line.split() for line in out.splitlines()):
                if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING" \
                        and parts[1].endswith(f":{port}") and parts[4].isdigit():
                    pids.add(int(parts[4]))
        else:
            out = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5).stdout
            pids.update(int(x) for x in out.split() if x.isdigit())
    return sorted(pids)


def port_owner(port: int) -> tuple[int, str] | None:
    """(pid, process name) listening on `port`, or None when it is free."""
    for pid in find_pids_by_port(port):
        name = "unknown"
        with contextlib.suppress(Exception):
            import psutil

            name = psutil.Process(pid).name()
        return pid, name
    return None


def _cmdline(pid: int) -> str:
    with contextlib.suppress(Exception):
        import psutil

        proc = psutil.Process(pid)
        return (proc.name() + " " + " ".join(proc.cmdline()[:6])).lower()
    return ""


def stop_by_port(ports: dict[str, int]) -> tuple[list[str], list[str]]:
    """Kill Atlas processes still holding Atlas's ports; leave anything else alone."""
    stopped, problems = [], []
    for label, port in ports.items():
        for pid in find_pids_by_port(port):
            cmd = _cmdline(pid)
            if not cmd or not any(m in cmd for m in OURS.get(label, ())):
                name = cmd.split()[0] if cmd else "unknown"
                problems.append(f"port {port} is held by PID {pid} ({name}), not Atlas: left alone")
                continue
            kill_pid_tree(pid)
            stopped.append(f"{label} on port {port} (PID {pid})")
    return stopped, problems


def http_ok(url: str, timeout: float = 1.5) -> bool:
    """A 2xx from `url` (llama-server's /health answers 503 while loading)."""
    try:
        return httpx.get(url, timeout=timeout).status_code < 300
    except httpx.HTTPError:
        return False


__all__ = [
    "LaunchedInfo",
    "find_pids_by_port",
    "fingerprint",
    "http_ok",
    "is_alive",
    "load_launched",
    "port_owner",
    "process_entry",
    "restart_required",
    "running",
    "stop_by_port",
    "write_launched",
]
