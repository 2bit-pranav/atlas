"""
Process supervision, process tree termination, and log plumbing.

Ensures that child processes are monitored, log-streamed with prefixes and
banners, and reliably terminated on Ctrl+C or shutdown without leaving orphan
workers holding network ports.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
TERM_GRACE_SECONDS = 2.0
BANNER_WIDTH = 66


class SpawnFailed(RuntimeError):
    """Raised when a child process fails to execute."""


def kill_pid_tree(pid: int, timeout: float = 2.0) -> None:
    """Forcefully terminate a process and all its child workers."""
    try:
        import psutil

        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for child in children:
            with contextlib.suppress(Exception):
                child.kill()
        with contextlib.suppress(Exception):
            proc.kill()
        _, alive = psutil.wait_procs([proc, *children], timeout=timeout)
        for survivor in alive:
            with contextlib.suppress(Exception):
                survivor.kill()
    except Exception:
        pass

    if IS_WINDOWS:
        # Definitive tree kill on Windows
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
            )


# --------------------------------------------------------------- Windows Job --

if IS_WINDOWS:
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
    JobObjectExtendedLimitInformation = 9

    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


class _WindowsJob:
    """Windows Job Object ensuring children terminate if handle closes."""

    def __init__(self) -> None:
        self._handle = None

    def open(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
        )
        if not kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(handle)
            return

        self._handle = handle

    def assign(self, pid: int) -> None:
        if self._handle is None:
            return
        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            return
        try:
            kernel32.AssignProcessToJobObject(self._handle, process)
        finally:
            kernel32.CloseHandle(process)

    def close(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


# ---------------------------------------------------------------- Log Relay --


def banner(sink: IO[str], name: str, title: str = "") -> None:
    label = f" {name} {title} ".rstrip()
    rule = "=" * BANNER_WIDTH
    sink.write(f"\n{rule}\n{label.center(BANNER_WIDTH)}\n{rule}\n")
    sink.flush()


class LogRelay:
    """Multiplexes stdout and stderr into a single synchronized console writer."""

    def __init__(
        self,
        name: str,
        sink: IO[str],
        *,
        ready_pattern: str | None = None,
        tail_lines: int = 200,
    ) -> None:
        self.name = name
        self._sink = sink
        self._lock = threading.Lock()
        self._ready_re = re.compile(ready_pattern) if ready_pattern else None
        self._queue: queue.Queue[str | None] = queue.Queue()
        self.ready = threading.Event()
        self.tail: deque[str] = deque(maxlen=tail_lines)

    def attach(self, proc: subprocess.Popen[bytes]) -> None:
        streams = [s for s in (proc.stdout, proc.stderr) if s is not None]
        for stream in streams:
            threading.Thread(target=self._read, args=(stream,), daemon=True).start()
        threading.Thread(target=self._write, args=(len(streams),), daemon=True).start()

    def _read(self, stream: IO[bytes]) -> None:
        try:
            for raw in iter(stream.readline, b""):
                text = raw.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                if self._ready_re is not None and self._ready_re.search(text):
                    self.ready.set()
                self._queue.put(text)
        except (ValueError, OSError):
            pass
        finally:
            self._queue.put(None)

    def _write(self, stream_count: int) -> None:
        closed = 0
        while closed < stream_count:
            item = self._queue.get()
            if item is None:
                closed += 1
                continue
            with self._lock:
                self.tail.append(item)
            try:
                self._sink.write(f"{time.strftime('%H:%M:%S')} [{self.name}] {item}\n")
                self._sink.flush()
            except (ValueError, OSError):
                pass

    def tail_text(self, lines: int = 15) -> str:
        with self._lock:
            return "\n".join(list(self.tail)[-lines:])


# ------------------------------------------------------------- ProcessGroup --


class ProcessGroup:
    """Manages active processes and handles orderly tree termination."""

    def __init__(self) -> None:
        self._children: list[tuple[str, subprocess.Popen[bytes]]] = []
        self._relays: dict[str, LogRelay] = {}
        self._job: _WindowsJob | None = _WindowsJob() if IS_WINDOWS else None
        if self._job is not None:
            self._job.open()

    def spawn(
        self,
        name: str,
        args: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        ready_pattern: str | None = None,
        sink: IO[str] | None = None,
    ) -> tuple[subprocess.Popen[bytes], LogRelay]:
        extra: dict = {}
        if not IS_WINDOWS:
            extra["start_new_session"] = True

        banner(sink or sys.stdout, name, "starting")
        try:
            proc = subprocess.Popen(
                args,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **extra,
            )
        except OSError as exc:
            raise SpawnFailed(
                f"could not start {name}: {args[0]!r} failed ({exc}). "
                "Check binary path and settings.json."
            ) from exc

        self._children.append((name, proc))

        relay = LogRelay(name, sink or sys.stdout, ready_pattern=ready_pattern)
        relay.attach(proc)
        self._relays[name] = relay

        if self._job is not None:
            with contextlib.suppress(OSError):
                self._job.assign(proc.pid)

        logger.info("started %s (pid %d)", name, proc.pid)
        return proc, relay

    def children(self) -> list[tuple[str, subprocess.Popen[bytes]]]:
        return list(self._children)

    def running(self) -> list[tuple[str, subprocess.Popen[bytes]]]:
        return [(n, p) for n, p in self._children if p.poll() is None]

    def stop(self, name: str, grace: float = TERM_GRACE_SECONDS, sink: IO[str] | None = None) -> None:
        """Stop one child by name and forget it, so it can be spawned again."""
        procs = [p for n, p in self._children if n == name and p.poll() is None]
        for proc in procs:
            banner(sink or sys.stdout, name, "stopping")
            logger.info("stopping %s (pid %d)", name, proc.pid)
            self._signal(proc, force=False)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(p.poll() is None for p in procs):
            time.sleep(0.1)
        for proc in procs:
            self._signal(proc, force=True)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
        self._children = [(n, p) for n, p in self._children if n != name]
        self._relays.pop(name, None)

    def shutdown(self, grace: float = TERM_GRACE_SECONDS, sink: IO[str] | None = None) -> None:
        alive = self.running()
        if not alive:
            return

        for name, proc in reversed(alive):
            banner(sink or sys.stdout, name, "stopping")
            logger.info("stopping %s (pid %d)", name, proc.pid)
            self._signal(proc, force=False)

        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and self.running():
            time.sleep(0.1)

        for name, proc in self.running():
            logger.warning("%s did not exit cleanly within %.1fs; killing process tree", name, grace)
            self._signal(proc, force=True)

        for _, proc in self.running():
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)

    def close(self, sink: IO[str] | None = None) -> None:
        self.shutdown(sink=sink)
        if self._job is not None:
            self._job.close()
            self._job = None

    @staticmethod
    def _signal(proc: subprocess.Popen[bytes], *, force: bool) -> None:
        if proc.poll() is not None:
            return
        try:
            if force:
                kill_pid_tree(proc.pid)
            elif IS_WINDOWS:
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


__all__ = ["LogRelay", "ProcessGroup", "SpawnFailed", "banner", "kill_pid_tree"]