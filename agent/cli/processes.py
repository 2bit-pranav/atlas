"""Child processes: spawning, log capture, and killing whole process trees.

Every line a child prints goes, unfiltered, to its service's log file and to a
callback; nothing here writes to the terminal. On Windows each child joins a
Job Object that kills it when Atlas exits, however it exits, so no orphan
keeps a port.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import IO, Callable

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
TERM_GRACE_SECONDS = 2.0
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class SpawnFailed(RuntimeError):
    """A child process could not be started at all."""


def kill_pid_tree(pid: int, timeout: float = 2.0) -> None:
    """Kill a process and everything it started."""
    try:
        import psutil

        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for p in [*children, proc]:
            with contextlib.suppress(Exception):
                p.kill()
        psutil.wait_procs([proc, *children], timeout=timeout)
    except Exception:  # noqa: BLE001 - already gone, or not ours to see
        pass
    if IS_WINDOWS:
        # psutil misses grandchildren that re-parent; taskkill /T does not.
        with contextlib.suppress(Exception):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)


# --------------------------------------------------------------- Windows Job --

if IS_WINDOWS:
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
    JobObjectExtendedLimitInformation = 9
    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

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
    """A Job Object whose children die when its handle closes (or Atlas dies)."""

    def __init__(self) -> None:
        self._handle = None
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK)
        if kernel32.SetInformationJobObject(handle, JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info)):
            self._handle = handle
        else:
            kernel32.CloseHandle(handle)

    def assign(self, pid: int) -> None:
        if self._handle is None:
            return
        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if process:
            try:
                kernel32.AssignProcessToJobObject(self._handle, process)
            finally:
                kernel32.CloseHandle(process)

    def close(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


# ------------------------------------------------------------------ capture --


class LogRelay:
    """Reads a child's stdout and stderr line by line.

    Each line is written to the log file with our timestamp and handed to
    `on_line` without colour codes. The last lines are kept for failure
    messages.
    """

    def __init__(self, service: str, log: IO[str], on_line: Callable[[str, str], None],
                 tail: int = 200) -> None:
        self.service = service
        self._log = log
        self._on_line = on_line
        self._lock = threading.Lock()
        self.tail: deque[str] = deque(maxlen=tail)

    def attach(self, proc: subprocess.Popen[bytes]) -> None:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream: IO[bytes]) -> None:
        try:
            for raw in iter(stream.readline, b""):
                text = _ANSI.sub("", raw.decode("utf-8", errors="replace")).rstrip()
                if not text.strip():
                    continue
                with self._lock:
                    self.tail.append(text)
                    with contextlib.suppress(ValueError, OSError):
                        self._log.write(f"{time.strftime('%H:%M:%S')} {text}\n")
                        self._log.flush()
                self._on_line(self.service, text)
        except (ValueError, OSError):
            pass

    def last(self, lines: int = 12) -> list[str]:
        with self._lock:
            return list(self.tail)[-lines:]


class ProcessGroup:
    """The children of one `atlas start`, stopped in reverse start order."""

    def __init__(self) -> None:
        self._children: dict[str, tuple[subprocess.Popen[bytes], LogRelay]] = {}
        #: Every service started at some point, so its port may need sweeping.
        self.spawned: set[str] = set()
        self._job = _WindowsJob() if IS_WINDOWS else None

    def spawn(self, service: str, args: list[str], *, log: IO[str],
              on_line: Callable[[str, str], None], cwd: Path | None = None,
              env: dict[str, str] | None = None) -> tuple[subprocess.Popen[bytes], LogRelay]:
        extra: dict = {} if IS_WINDOWS else {"start_new_session": True}
        try:
            proc = subprocess.Popen(args, cwd=str(cwd) if cwd else None, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, **extra)
        except OSError as exc:
            raise SpawnFailed(f"could not run {args[0]!r}: {exc}") from exc
        relay = LogRelay(service, log, on_line)
        relay.attach(proc)
        if self._job is not None:
            self._job.assign(proc.pid)
        self._children[service] = (proc, relay)
        self.spawned.add(service)
        logger.debug("started %s (pid %d)", service, proc.pid)
        return proc, relay

    def get(self, service: str) -> tuple[subprocess.Popen[bytes], LogRelay] | None:
        return self._children.get(service)

    def running(self) -> dict[str, subprocess.Popen[bytes]]:
        return {s: p for s, (p, _) in self._children.items() if p.poll() is None}

    def stop(self, service: str, grace: float = TERM_GRACE_SECONDS) -> None:
        """Stop one child and forget it, so it can be spawned again."""
        entry = self._children.pop(service, None)
        if entry is None:
            return
        proc = entry[0]
        if proc.poll() is None:
            self._signal(proc, force=False)
            deadline = time.monotonic() + grace
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self._signal(proc, force=True)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)

    def close(self) -> None:
        for service in reversed(list(self._children)):
            self.stop(service)
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


__all__ = ["LogRelay", "ProcessGroup", "SpawnFailed", "kill_pid_tree"]
