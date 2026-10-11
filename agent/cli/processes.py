"""Process supervision and log plumbing for the launcher (spec section 3, L1).

Atlas' contract is blunt: one CLI starts everything, and force-quitting the CLI
kills all of it -- including ``llama-server``, which would otherwise sit on the
VRAM and block the next launch. Section 3 flags this as the thing to test early.

Getting that right is platform-shaped:

* **Windows** - children are assigned to a Job Object with
  ``KILL_ON_JOB_CLOSE``. When the CLI dies for *any* reason (Ctrl+C, closing the
  console window, a hard kill, a Python exception), the OS closes the handle and
  the kernel terminates every process in the job. Child-killing is therefore not
  something the CLI has to remember to do.
* **POSIX** - children go in a new process group via ``start_new_session`` and we
  signal the negated group pid. Slightly weaker: it does not survive SIGKILL of
  the CLI itself, which is the trade the platform offers.

Both paths also do an explicit, ordered shutdown on the normal Ctrl+C path so
that llama-server gets a chance to release the GPU rather than being torn down.

Log plumbing matters as much as the killing. Three components will each write a
continuous stream (llama's model loading and token chatter, uvicorn's access
log, the client's dev server), so output is captured rather than inherited and
re-emitted with a timestamp and a ``[name]`` prefix, separated by banner lines.
"""

from __future__ import annotations

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

# Grace period between "please stop" and "stop now".
TERM_GRACE_SECONDS = 8.0

BANNER_WIDTH = 66


class SpawnFailed(RuntimeError):
    """A child process could not be started at all (usually a missing binary)."""


# --------------------------------------------------------------- Windows job --

if IS_WINDOWS:
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
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
    """A Job Object that kills its members when the handle closes."""

    def __init__(self) -> None:
        self._handle = None

    def open(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError()

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(handle)
            raise ctypes.WinError()

        self._handle = handle

    def assign(self, pid: int) -> None:
        if self._handle is None:
            raise RuntimeError("job not open")
        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not process:
            raise ctypes.WinError()
        try:
            if not kernel32.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError()
        finally:
            kernel32.CloseHandle(process)

    def close(self) -> None:
        """Closing the handle is what kills the job. Called on the way out."""
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


# ---------------------------------------------------------------- log relay ----


def banner(sink: IO[str], name: str, title: str = "") -> None:
    """A visual separator so interleaved component logs stay readable."""
    label = f" {name} {title} ".rstrip()
    rule = "=" * BANNER_WIDTH
    sink.write(f"\n{rule}\n{label.center(BANNER_WIDTH)}\n{rule}\n")
    sink.flush()


class LogRelay:
    """Pumps a child's stdout and stderr into the console, prefixed.

    Also watches the stream for a readiness marker. llama.cpp announces itself
    with ``srv  ...: listening on http://127.0.0.1:8080/``, which is far better
    than blind-polling: no wasted requests, and the terminal is not filled with
    connection-refused noise while the model loads.

    Reader threads never write to the sink directly -- they hand lines to a
    queue and a single writer drains it. Writing straight from the readers looks
    simpler but deadlocks: if the sink is slow or blocked (``atlas up | tee``,
    a stalled terminal), the reader stops draining the child's pipe, the pipe
    fills, and the child can never exit during shutdown.
    """

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
        """Start reader threads per pipe plus the single writer thread."""
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
                # Detect readiness here, not in the writer: it must not depend
                # on how fast the sink accepts output.
                if self._ready_re is not None and self._ready_re.search(text):
                    self.ready.set()
                self._queue.put(text)
        except (ValueError, OSError):
            # Pipe closed underneath us during shutdown.
            pass
        finally:
            self._queue.put(None)

    def _write(self, stream_count: int) -> None:
        """The only thread that touches the sink.

        Runs until every reader has closed (one sentinel each). It must consume
        *all* queued lines, not just the first few: the readers are what keep
        the child's pipes from filling up, so dropping items here would wedge
        the child exactly when we are trying to shut it down.
        """
        sink_ok = True
        closed = 0
        while closed < stream_count:
            item = self._queue.get()
            if item is None:
                closed += 1
                continue
            with self._lock:
                self.tail.append(item)
            if not sink_ok:
                # Sink died (the CLI is exiting). Keep draining regardless.
                continue
            try:
                self._sink.write(f"{time.strftime('%H:%M:%S')} [{self.name}] {item}\n")
                self._sink.flush()
            except (ValueError, OSError):
                sink_ok = False

    def tail_text(self, lines: int = 15) -> str:
        """Last N lines, for a failure message. Newest last."""
        with self._lock:
            return "\n".join(list(self.tail)[-lines:])


# ---------------------------------------------------------------- ProcessGroup --


class ProcessGroup:
    """Owns every child Atlas spawns and guarantees they all die with us."""

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
        """Start a child in the group, capturing its output.

        Output is piped rather than inherited: inherited output would bypass the
        prefix and the banners entirely, which is what made llama-server's log
        indistinguishable from the CLI's own.
        """
        extra: dict = {}
        if not IS_WINDOWS:
            # Own session => own process group => one signal reaches all of it.
            extra["start_new_session"] = True

        banner(sink or sys.stdout, name, "starting")
        try:
            proc = subprocess.Popen(  # noqa: S603
                args,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **extra,
            )
        except OSError as exc:
            # Almost always a missing binary. Say which one, instead of letting
            # a bare WinError 2 escape and take down the launcher.
            raise SpawnFailed(
                f"could not start {name}: {args[0]!r} could not be executed "
                f"({exc}). Check the binary in settings.json and that it is on PATH."
            ) from exc
        self._children.append((name, proc))

        relay = LogRelay(
            name, sink or sys.stdout, ready_pattern=ready_pattern
        )
        relay.attach(proc)
        self._relays[name] = relay

        if self._job is not None:
            try:
                self._job.assign(proc.pid)
            except OSError:
                # Already inside a job (launched from an IDE or CI runner).
                # Explicit shutdown still applies; only the hard-kill backstop
                # is unavailable.
                logger.warning("%s (pid %d) could not join the job object", name, proc.pid)

        logger.info("started %s (pid %d)", name, proc.pid)
        return proc, relay

    def relay(self, name: str) -> LogRelay | None:
        return self._relays.get(name)

    def children(self) -> list[tuple[str, subprocess.Popen[bytes]]]:
        """Every child this group started, running or not."""
        return list(self._children)

    def running(self) -> list[tuple[str, subprocess.Popen[bytes]]]:
        return [(n, p) for n, p in self._children if p.poll() is None]

    def shutdown(self, grace: float = TERM_GRACE_SECONDS, sink: IO[str] | None = None) -> None:
        """Ask nicely, then insist. Reverse order: backend before the model."""
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
            logger.warning("%s did not exit in %.0fs; killing", name, grace)
            self._signal(proc, force=True)

        for _, proc in self.running():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                logger.error("pid %d would not die", proc.pid)

    def close(self, sink: IO[str] | None = None) -> None:
        """Release the job handle. On Windows this is what kills any stragglers."""
        self.shutdown(sink=sink)
        if self._job is not None:
            self._job.close()
            self._job = None

    @staticmethod
    def _signal(proc: subprocess.Popen[bytes], *, force: bool) -> None:
        if proc.poll() is not None:
            return
        try:
            if IS_WINDOWS:
                proc.kill() if force else proc.terminate()
            elif force:
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            logger.debug("signal to pid %s failed: %s", proc.pid, exc)


__all__ = ["LogRelay", "ProcessGroup", "SpawnFailed", "banner"]
