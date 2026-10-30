"""B7: stopping a service ends everything it started (agent/cli/procs.py).

Before: on Windows the graceful stop killed the child only, so the tree kill
that followed found it gone and returned; and the job object let grandchildren
break away silently. MCP servers and Vite's node outlived every stop and restart.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil
import pytest

from agent.cli.procs import IS_WINDOWS, ProcessGroup

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="the Windows process tree and job object")

PARENT = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
print(f"grandchild {child.pid}", flush=True)
time.sleep(120)
"""


def _start(tmp_path: Path) -> tuple[ProcessGroup, int]:
    script = tmp_path / "parent.py"
    script.write_text(PARENT, encoding="utf-8")
    lines: list[str] = []
    group = ProcessGroup()
    group.spawn("svc", [sys.executable, str(script)], log=(tmp_path / "svc.log").open("w", encoding="utf-8"),
                on_line=lambda _service, line: lines.append(line))
    deadline = time.time() + 20
    while time.time() < deadline and not any(line.startswith("grandchild") for line in lines):
        time.sleep(0.1)
    found = next((line for line in lines if line.startswith("grandchild")), None)
    assert found, "the test parent did not start its child"
    return group, int(found.split()[1])


def _gone(pid: int, timeout: float = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.1)
    return False


def test_stop_ends_the_whole_tree(tmp_path) -> None:
    group, grandchild = _start(tmp_path)
    try:
        group.stop("svc", grace=1)
        assert _gone(grandchild), "the grandchild outlived the stop"
    finally:
        psutil.Process(grandchild).kill() if psutil.pid_exists(grandchild) else None
        group.close()


def test_closing_the_job_ends_grandchildren(tmp_path) -> None:
    """However Atlas exits, the job closes, and nothing it started survives."""
    group, grandchild = _start(tmp_path)
    try:
        assert group._job is not None
        group._job.close()
        assert _gone(grandchild), "the grandchild was not in the job"
    finally:
        psutil.Process(grandchild).kill() if psutil.pid_exists(grandchild) else None
        group.close()
