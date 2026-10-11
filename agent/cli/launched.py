"""``launched.json``: what is actually running right now (spec section 3, L1).

Written once at launch. Three jobs:

1. Give every run a ``launch_id`` to record, so a run can tell which build and
   which settings produced it.
2. Pin the things tool-call behaviour depends on: the llama.cpp build, the GGUF
   and mmproj hashes, and the exact flag list. Section 9.1.1 requires re-running
   L0b when any of those change, because parser and template bugs move between
   builds.
3. Hold the restart-tier slice actually used, so the API can diff the file
   against it and report "restart required".

Hashing a multi-GB GGUF on every launch is wasteful, so results are cached
keyed on (path, size, mtime).
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from agent.cli.settings import Tier, changed_restart_keys, restart_tier_values
from agent.ids import new_ulid

if TYPE_CHECKING:
    from agent.cli.processes import LogRelay

IS_WINDOWS = sys.platform == "win32"

_HASH_CHUNK = 1024 * 1024

def new_launch_id() -> str:
    """The launch id is a ULID, same as every other row id (spec section 5)."""
    return new_ulid()


def hash_file(path: Path) -> str | None:
    """SHA-256 of a file, or None if it does not exist."""
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
    """The contents of ``launched.json``."""

    launch_id: str
    started_at: int
    llama_base_url: str
    llamacpp_build: str | None = None
    llamacpp_args: list[str] = field(default_factory=list)
    model_path: str | None = None
    model_sha256: str | None = None
    mmproj_sha256: str | None = None
    llama_pid: int | None = None
    #: pid -> {"create_time": epoch, "cmdline": str}. Lets `atlas down` stop a
    #: stack started from a *different* terminal, where no in-process handle
    #: exists. Identity is verified before killing, so a recycled pid belonging
    #: to something else is never touched.
    processes: dict[str, Any] = field(default_factory=dict)
    backend_url: str | None = None
    restart_settings: dict[str, Any] = field(default_factory=dict)
    # Cache keys so an unchanged GGUF is not re-hashed on every launch.
    model_fingerprint: dict[str, Any] | None = None
    mmproj_fingerprint: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LaunchedInfo:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def record_process(info: LaunchedInfo, name: str, proc: "subprocess.Popen[bytes] | object") -> None:
    """Remember a started child so ``atlas down`` can find it later."""
    pid = getattr(proc, "pid", None)
    if pid is None:
        return
    entry: dict[str, Any] = {"pid": pid, "create_time": None, "cmdline": None}
    try:
        import psutil

        native = psutil.Process(pid)
        entry["create_time"] = native.create_time()
        entry["cmdline"] = " ".join(native.cmdline()[:4])
    except Exception:  # noqa: BLE001 - psutil missing or process gone
        pass
    info.processes[name] = entry


def _matches(entry: dict[str, Any]) -> bool:
    """Is this still the process we started?

    Guards against killing an unrelated process that happens to hold the same
    pid after a reboot or a long-running session.
    """
    pid = entry.get("pid")
    if not pid:
        return False
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a hard dependency
        return False
    try:
        proc = psutil.Process(int(pid))
    except Exception:  # noqa: BLE001 - gone, which is fine
        return False
    recorded_start = entry.get("create_time")
    if recorded_start is not None:
        try:
            if abs(proc.create_time() - float(recorded_start)) > 2.0:
                return False
        except Exception:  # noqa: BLE001
            return False
    return proc.is_running()


def stop_recorded(
    info: LaunchedInfo | None, *, grace: float = 10.0
) -> tuple[list[str], list[str]]:
    """Stop the children recorded in ``launched.json``.

    Backend first, then the model, mirroring the launcher's own shutdown order.
    Returns ``(stopped, problems)``.
    """
    if info is None or not info.processes:
        return [], ["no launched.json, so no processes are known"]

    stopped: list[str] = []
    problems: list[str] = []
    order = ["backend", "llama"]

    for name in order:
        entry = info.processes.get(name)
        if not entry:
            continue
        pid = int(entry["pid"])
        if not _matches(entry):
            problems.append(f"{name} (pid {pid}) is not running any more")
            continue
        try:
            import psutil

            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                with contextlib.suppress(Exception):
                    child.terminate()
            proc.terminate()
            gone, alive = psutil.wait_procs([proc], timeout=grace)
            for survivor in alive:
                survivor.kill()
            stopped.append(f"{name} (pid {pid})")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"could not stop {name} (pid {pid}): {exc}")

    return stopped, problems


def find_by_port(port: int) -> tuple[int, str] | None:
    """Find the process listening on ``port``: ``(pid, cmdline)``.

    A fallback for when ``launched.json`` is missing or has no pids -- which
    happens if the file was deleted, or an older launch wrote it. Verified by
    the caller before anything is killed.
    """
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                continue
            if conn.laddr.port != port or not conn.pid:
                continue
            try:
                cmdline = " ".join(psutil.Process(conn.pid).cmdline()[:6])
            except Exception:  # noqa: BLE001
                cmdline = ""
            return int(conn.pid), cmdline
    except Exception:  # noqa: BLE001 - access denied on some systems
        return None
    return None


def stop_by_port(ports: dict[str, int]) -> tuple[list[str], list[str]]:
    """Fallback stop: locate the stack by its ports and terminate it.

    Only processes whose command line looks like *ours* are touched, so an
    unrelated service on the same port is reported rather than killed.
    """
    stopped: list[str] = []
    problems: list[str] = []
    markers = ("llama", "serve", "uvicorn", "agent.server.main")

    # Backend before the model, matching the launcher's own shutdown order.
    for label in ("backend", "llama"):
        port = ports.get(label)
        if not port:
            continue
        found = find_by_port(port)
        if found is None:
            problems.append(f"nothing is listening on {port} ({label})")
            continue
        pid, cmdline = found
        if not any(marker in cmdline.lower() for marker in markers):
            problems.append(
                f"port {port} is held by pid {pid}, which is not ours; not touching it "
                f"(cmd: {cmdline[:70]})"
            )
            continue
        try:
            import psutil

            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                with contextlib.suppress(Exception):
                    child.terminate()
            proc.terminate()
            _, alive = psutil.wait_procs([proc], timeout=10)
            for survivor in alive:
                survivor.kill()
            stopped.append(f"{label} on port {port} (pid {pid}, found by port)")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"could not stop pid {pid} on port {port}: {exc}")

    return stopped, problems


def probe_llamacpp_build(base_url: str, timeout: float = 5.0) -> str | None:
    """Read ``build_info`` from a running server, if one is up."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/props", timeout=timeout)
        response.raise_for_status()
        return response.json().get("build_info")
    except Exception:  # noqa: BLE001
        return None


def wait_for_health(
    base_url: str,
    timeout: float = 60.0,
    interval: float = 0.5,
    *,
    until: threading.Event | None = None,
    watch_pid: int | None = None,
) -> bool:
    """Poll ``/health`` until the server answers, times out, or the child dies.

    This is the *fallback* path. The normal path waits for llama.cpp's own
    "listening on" line in the child's output (see LogRelay) and then calls this
    once, so no requests are wasted while a 2 GB model is loading and the
    terminal stays quiet.

    ``until`` lets a caller stop waiting early (e.g. the child exited).
    """
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
        except Exception:  # noqa: BLE001 - not up yet; that is the normal case
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _pid_alive(pid: int) -> bool:
    """True while the process exists (Windows and POSIX)."""
    if IS_WINDOWS:
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # SYNCHRONIZE
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
    proc: "subprocess.Popen[bytes] | None",
    relay: "LogRelay | None",
    base_url: str,
    *,
    timeout: float,
    safety_probe_interval: float = 5.0,
) -> tuple[bool, str]:
    """Wait for a spawned llama-server without hammering the port.

    The readiness *line* is a hint, not the authority. llama.cpp's format is
    ``srv  %12.*s: listening on %s`` and the padding before it varies between
    builds, so only the stable tail ("listening on ") is matched. A single
    ``/health`` call is the authority, and it confirms the hint.

    Two intervals keep the terminal and the port quiet:
      * once the line is seen, probe eagerly (~0.2s) - normally this is the
        very first request the CLI makes, seconds after the model loads;
      * before that, probe only every ``safety_probe_interval`` as a backstop
        for an older build, redirected output, or a future format change.

    Returns ``(ok, reason)``.
    """
    deadline = time.monotonic() + timeout
    next_safety_probe = 0.0
    url = f"{base_url.rstrip('/')}/health"

    while True:
        if proc is not None and proc.poll() is not None:
            return False, f"the server process exited with code {proc.returncode}"

        announced = relay is not None and relay.ready.is_set()
        now = time.monotonic()

        # Eager only after the announcement; otherwise a slow safety probe.
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
            except Exception:  # noqa: BLE001 - not up yet; that is the normal case
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
    """Assemble launched.json, reusing cached hashes when the file is unchanged."""

    model_fp = _file_fingerprint(Path(model_path)) if model_path else None
    mmproj_fp = _file_fingerprint(Path(mmproj_path)) if mmproj_path else None

    def _hash(fp: dict[str, Any] | None, cached_fp, cached_hash) -> str | None:
        if fp is None:
            return None
        if cached_fp == fp and cached_hash:
            return cached_hash
        return hash_file(Path(fp["path"]))

    model_hash = _hash(model_fp, previous.model_fingerprint if previous else None,
                       previous.model_sha256 if previous else None)
    mmproj_hash = _hash(mmproj_fp, previous.mmproj_fingerprint if previous else None,
                        previous.mmproj_sha256 if previous else None)

    # Carry over the pids of components this launch did NOT start. A second
    # `atlas up` against an already-running stack must not erase the records
    # that let `atlas down` find and stop it.
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
    """Write atomically so a crash mid-write cannot leave a truncated file."""
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
    """Restart-tier keys that differ from what is running. Empty means up to date.

    Nothing launched yet counts as "everything needs restarting".
    """
    if launched is None:
        return restart_tier_values(settings_dict)
    return changed_restart_keys(settings_dict, launched.restart_settings)


__all__ = [
    "LaunchedInfo",
    "Tier",
    "build_launched_info",
    "changed_restart_keys",
    "hash_file",
    "load_launched",
    "new_launch_id",
    "probe_llamacpp_build",
    "restart_required",
    "wait_for_health",
    "wait_until_ready",
    "write_launched",
]
