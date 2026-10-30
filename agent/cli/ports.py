"""Who holds a port, and stopping what Atlas started on its ports (only processes
whose command line is Atlas's own: llama, uvicorn, vite)."""


from __future__ import annotations

import contextlib
import subprocess

import httpx

from agent.cli.launched import IS_WINDOWS
from agent.cli.procs import kill_pid_tree

#: What each service's process looks like; a port holder that does not match
#: its service is someone else's program and is left alone.
OURS = {"llama": ("llama",), "backend": ("uvicorn", "server.main"), "web": ("vite", "node", "npm")}


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


__all__ = ["OURS", "find_pids_by_port", "http_ok", "port_owner", "stop_by_port"]
