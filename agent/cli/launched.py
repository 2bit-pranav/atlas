"""
launched.json tracking, port inspection, and process termination helpers.

Maintains runtime status and provides port-scanning to ensure
no orphaned processes linger across launches.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from agent.cli.processes import kill_pid_tree
from agent.core.ids import new_ulid
from agent.core.settings import changed_restart_keys, restart_tier_values

if TYPE_CHECKING:
    from agent.cli.processes import LogRelay

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
_HASH_CHUNK = 1024 * 1024


def new_launch_id() -> str:
    return new_ulid()


def hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _file_fingerprint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


@dataclass
class LaunchedInfo:
    launch_id: str
    started_at: int
    llama_base_url: str
    llamacpp_build: str | None = None
    llamacpp_args: list[str] = field(default_factory=list)
    model_path: str | None = None
    model_sha256: str | None = None
    mmproj_sha256: str | None = None
    llama_pid: int | None = None
    processes: dict[str, Any] = field(default_factory=dict)
    backend_url: str | None = None
    restart_settings: dict[str, Any] = field(default_factory=dict)
    model_fingerprint: dict[str, Any] | None = None
    mmproj_fingerprint: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LaunchedInfo:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def record_process(info: LaunchedInfo, name: str, proc: Any) -> None:
    pid = getattr(proc, "pid", None)
    if pid is None and isinstance(proc, int):
        pid = proc
    if pid is None:
        return
    entry: dict[str, Any] = {"pid": pid, "create_time": None, "cmdline": None}
    try:
        import psutil

        native = psutil.Process(pid)
        entry["create_time"] = native.create_time()
        entry["cmdline"] = " ".join(native.cmdline()[:4])
    except Exception:
        pass
    info.processes[name] = entry


def _matches(entry: dict[str, Any]) -> bool:
    pid = entry.get("pid")
    if not pid:
        return False
    try:
        import psutil

        proc = psutil.Process(int(pid))
        recorded_start = entry.get("create_time")
        if recorded_start is not None:
            if abs(proc.create_time() - float(recorded_start)) > 2.0:
                return False
        return proc.is_running()
    except Exception:
        return False


def stop_recorded(
    info: LaunchedInfo | None, *, grace: float = 2.0
) -> tuple[list[str], list[str]]:
    if info is None or not info.processes:
        return [], ["no launched.json found or no processes recorded"]

    stopped: list[str] = []
    problems: list[str] = []
    order = ["frontend", "client", "backend", "llama"]

    for name in order:
        entry = info.processes.get(name)
        if not entry:
            continue
        pid = int(entry["pid"])
        if not _matches(entry):
            continue
        try:
            kill_pid_tree(pid, timeout=grace)
            stopped.append(f"{name} (pid {pid})")
        except Exception as exc:
            problems.append(f"could not stop {name} (pid {pid}): {exc}")

    return stopped, problems


def find_pids_by_port(port: int) -> list[int]:
    """Identify all PIDs listening on the specified port."""
    pids: set[int] = set()

    # 1. psutil
    try:
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            if (
                conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and conn.laddr.port == port
                and conn.pid
            ):
                pids.add(conn.pid)
    except Exception:
        pass

    # 2. Windows fallback using netstat
    if IS_WINDOWS and not pids:
        try:
            res = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if (
                    len(parts) >= 5
                    and parts[0].upper() == "TCP"
                    and parts[3].upper() == "LISTENING"
                ):
                    local_addr = parts[1]
                    if local_addr.endswith(f":{port}"):
                        with contextlib.suppress(ValueError):
                            pids.add(int(parts[4]))
        except Exception:
            pass

    # 3. POSIX fallback using lsof
    if not IS_WINDOWS and not pids:
        try:
            res = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
        except Exception:
            pass

    return sorted(pids)


def stop_by_port(ports: dict[str, int]) -> tuple[list[str], list[str]]:
    """Scan configured ports and terminate any lingering processes."""
    stopped: list[str] = []
    problems: list[str] = []
    markers = (
        "llama", "serve", "uvicorn", "server.main",
        "vite", "npm", "node", "python", "atlas"
    )

    for label in ("frontend", "client", "backend", "llama"):
        port = ports.get(label)
        if not port:
            continue
        pids = find_pids_by_port(port)
        for pid in pids:
            cmdline = ""
            name = ""
            try:
                import psutil

                p = psutil.Process(pid)
                name = p.name().lower()
                cmdline = " ".join(p.cmdline()[:6]).lower()
            except Exception:
                pass

            is_ours = any(m in cmdline or m in name for m in markers) or not cmdline
            if not is_ours:
                problems.append(
                    f"port {port} is held by pid {pid}, which does not match Atlas markers (cmd: {cmdline[:60]})"
                )
                continue

            try:
                kill_pid_tree(pid)
                stopped.append(f"{label} on port {port} (pid {pid})")
            except Exception as exc:
                problems.append(f"could not stop pid {pid} on port {port}: {exc}")

    return stopped, problems


def probe_llamacpp_build(base_url: str, timeout: float = 5.0) -> str | None:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/props", timeout=timeout)
        response.raise_for_status()
        return response.json().get("build_info")
    except Exception:
        return None


def wait_for_health(
    base_url: str,
    timeout: float = 60.0,
    interval: float = 0.5,
    *,
    until: threading.Event | None = None,
    watch_pid: int | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    url = f"{base_url.rstrip('/')}/health"
    while True:
        if until is not None and until.is_set():
            return False
        if watch_pid is not None and not _pid_alive(watch_pid):
            return False
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def wait_for_http(url: str, timeout: float = 5.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if httpx.get(url, timeout=1.0).status_code < 500:
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_until_ready(
    proc: subprocess.Popen[bytes] | None,
    relay: LogRelay | None,
    base_url: str,
    *,
    timeout: float,
    safety_probe_interval: float = 5.0,
) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout
    next_safety_probe = 0.0
    url = f"{base_url.rstrip('/')}/health"

    while True:
        if proc is not None and proc.poll() is not None:
            return False, f"the server process exited with code {proc.returncode}"

        announced = relay is not None and relay.ready.is_set()
        now = time.monotonic()

        probe_now = announced or now >= next_safety_probe
        if probe_now and not announced:
            next_safety_probe = now + safety_probe_interval

        if probe_now:
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    saw_line = relay is not None and relay.ready.is_set()
                    return True, (
                        "server announced readiness, confirmed over HTTP"
                        if saw_line
                        else "detected by probing; the server printed no readiness line"
                    )
            except Exception:
                pass

        if now >= deadline:
            return False, f"timed out after {timeout:.0f}s waiting for the server"
        time.sleep(0.2)


def build_launched_info(
    *,
    llama_base_url: str,
    llama_args: list[str],
    settings_dict: dict[str, Any],
    model_path: str | None,
    mmproj_path: str | None,
    previous: LaunchedInfo | None = None,
    llama_pid: int | None = None,
) -> LaunchedInfo:
    model_fp = _file_fingerprint(Path(model_path)) if model_path else None
    mmproj_fp = _file_fingerprint(Path(mmproj_path)) if mmproj_path else None

    def _hash(fp: dict[str, Any] | None, cached_fp, cached_hash) -> str | None:
        if fp is None:
            return None
        if cached_fp == fp and cached_hash:
            return cached_hash
        return hash_file(Path(fp["path"]))

    model_hash = _hash(
        model_fp,
        previous.model_fingerprint if previous else None,
        previous.model_sha256 if previous else None,
    )
    mmproj_hash = _hash(
        mmproj_fp,
        previous.mmproj_fingerprint if previous else None,
        previous.mmproj_sha256 if previous else None,
    )

    processes: dict[str, Any] = {}
    if previous and previous.processes:
        processes.update(previous.processes)

    return LaunchedInfo(
        launch_id=new_launch_id(),
        started_at=int(time.time() * 1000),
        llama_base_url=llama_base_url,
        llamacpp_build=probe_llamacpp_build(llama_base_url),
        llamacpp_args=list(llama_args),
        model_path=model_fp["path"] if model_fp else model_path,
        model_sha256=model_hash,
        mmproj_sha256=mmproj_hash,
        llama_pid=llama_pid,
        processes=processes,
        backend_url=previous.backend_url if previous else None,
        restart_settings=restart_tier_values(settings_dict),
        model_fingerprint=model_fp,
        mmproj_fingerprint=mmproj_fp,
    )


def write_launched(path: Path, info: LaunchedInfo) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(info.to_json(), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_launched(path: Path) -> LaunchedInfo | None:
    if not path.exists():
        return None
    try:
        return LaunchedInfo.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None


def restart_required(settings_dict: dict[str, Any], launched: LaunchedInfo | None) -> dict[str, Any]:
    if launched is None:
        return restart_tier_values(settings_dict)
    return changed_restart_keys(settings_dict, launched.restart_settings)