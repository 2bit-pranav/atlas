"""
Atlas CLI: start, stop, and settings.

Primary commands:
  atlas start     Start llama-server, FastAPI backend, and Vite frontend
  atlas stop      Stop all running Atlas processes and verify ports are free
  atlas settings  Validate or display `settings.json`
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from agent.cli.launch import (
    build_backend_args,
    build_frontend_args,
    build_llamacpp_args,
    describe_args,
)
from agent.cli.launched import (
    build_launched_info,
    find_pids_by_port,
    load_launched,
    record_process,
    restart_required,
    stop_by_port,
    stop_recorded,
    wait_for_health,
    wait_until_ready,
    write_launched,
)
from agent.cli.processes import ProcessGroup, SpawnFailed, banner, kill_pid_tree
from agent.core import llama, paths
from agent.core.settings import Settings, SettingsError, load_settings

logger = logging.getLogger("atlas")


def _find_repo_root() -> Path:
    """Locate the project root so CLI runs reliably from any subdirectory."""
    file_root = Path(__file__).resolve().parents[2]
    if (file_root / "settings.example.json").is_file() or (file_root / "pyproject.toml").is_file():
        return file_root
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / "settings.example.json").is_file() or (p / "pyproject.toml").is_file():
            return p
    return cur


REPO_ROOT = _find_repo_root()
DEFAULT_SETTINGS = str(REPO_ROOT / "settings.json")
DEFAULT_LAUNCHED = str(REPO_ROOT / "launched.json")

_shutting_down = False


def _load_or_die(path: Path) -> Settings:
    try:
        return load_settings(path)
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


def _print_restart_status(settings: Settings, launched_path: Path) -> list[str]:
    changed = restart_required(settings.model_dump(mode="json"), load_launched(launched_path))
    if not changed:
        print("restart required: no (settings match the running launch)")
    else:
        print("restart required: yes")
        for key, value in sorted(changed.items()):
            print(f"  {key} = {value!r}")
    return sorted(changed)


# ------------------------------------------------------------------- commands --


def cmd_settings_check(args: argparse.Namespace) -> int:
    settings = _load_or_die(Path(args.settings))
    print(f"{args.settings}: OK")
    print(f"  models folder     = {paths.models_dir(settings)}")
    print(f"  model             = {settings.model.name}")
    print(f"  context_size      = {settings.model.context_size}")
    print(f"  parallel_slots    = {settings.model.parallel_slots}")
    print(f"  llama port        = {settings.ports.llama}")
    print(f"  backend port      = {settings.ports.backend}")
    print(f"  frontend port     = {settings.ports.client}")
    print(f"  llama-server args = {describe_args(build_llamacpp_args(settings))}")
    return 0


def cmd_settings_show(args: argparse.Namespace) -> int:
    settings = _load_or_die(Path(args.settings))
    if args.restart_required:
        _print_restart_status(settings, Path(args.launched))
        return 0
    print(json.dumps(settings.model_dump(mode="json"), indent=2))
    return 0


def _start_llama(group: ProcessGroup, settings: Settings, args: argparse.Namespace,
                 root: Path) -> tuple[int | None, str | None]:
    """Spawn llama-server with the chosen model and wait until it serves.

    Returns (pid, error). On an error nothing is left running.
    """
    try:
        llama_args = build_llamacpp_args(settings)
    except llama.ModelError as exc:
        return None, f"{exc}. Pick one under Settings > Model."
    base_url = f"http://127.0.0.1:{settings.ports.llama}"
    started = time.monotonic()
    try:
        proc, relay = group.spawn("llama", llama_args, cwd=root, ready_pattern=r"listening on ",
                                  sink=sys.stdout)
    except SpawnFailed as exc:
        return None, str(exc)
    logger.info("waiting for llama-server to load %r (up to %.0fs)...", settings.model.name, args.health_timeout)
    ok, reason = wait_until_ready(proc, relay, base_url, timeout=args.health_timeout)
    if not ok:
        tail = relay.tail_text()
        if tail:
            logger.error("last output from llama-server:\n%s", tail)
        group.stop("llama")
        return None, f"llama-server did not start with {settings.model.name!r}: {reason}"
    logger.info("llama-server ready in %.1fs (%s)", time.monotonic() - started, reason)
    return proc.pid, None


def _start_backend(group: ProcessGroup, settings: Settings, args: argparse.Namespace, root: Path,
                   launched_path: Path) -> Any:
    """Spawn the backend. It can ask for a restart through the request file."""
    stale = find_pids_by_port(settings.ports.backend)
    if stale:
        banner(sys.stdout, "backend", f"clearing stale process on port {settings.ports.backend}")
        for pid in stale:
            kill_pid_tree(pid)
        time.sleep(0.5)
    env = dict(os.environ)
    env["ATLAS_SETTINGS"] = str(Path(args.settings).resolve())
    env["ATLAS_ROOT"] = str(root)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    request, status = _restart_files(launched_path)
    env["ATLAS_RESTART_REQUEST"] = str(request)
    env["ATLAS_RESTART_STATUS"] = str(status)
    env["ATLAS_LAUNCHED"] = str(launched_path.resolve())
    backend, _ = group.spawn("backend", build_backend_args(settings), cwd=root, env=env, sink=sys.stdout)
    logger.info("backend starting on http://127.0.0.1:%d", settings.ports.backend)
    return backend


def _restart_files(launched_path: Path) -> tuple[Path, Path]:
    """The backend creates the first to ask for a restart; the second says how it went."""
    return launched_path.with_name("restart.request"), launched_path.with_name("restart.json")


def _write_status(path: Path, state: str, **fields: Any) -> None:
    path.write_text(json.dumps({"state": state, "at": int(time.time() * 1000), **fields}), encoding="utf-8")


def _record(launched_path: Path, settings: Settings, group: ProcessGroup, llama_pid: int | None) -> None:
    """launched.json: what is running, and the settings it was started with."""
    try:
        chosen = llama.current(settings)
        model_file, mmproj_file = str(chosen.gguf), str(chosen.mmproj) if chosen.mmproj else None
    except llama.ModelError:
        model_file = mmproj_file = None
    try:
        llama_args = build_llamacpp_args(settings)
    except llama.ModelError:
        llama_args = []
    info = build_launched_info(
        llama_base_url=f"http://127.0.0.1:{settings.ports.llama}",
        llama_args=llama_args,
        settings_dict=settings.model_dump(mode="json"),
        model_path=model_file,
        mmproj_path=mmproj_file,
        previous=load_launched(launched_path),
        llama_pid=llama_pid,
    )
    info.processes = {}
    if llama_pid:
        record_process(info, "llama", llama_pid)
    for name, proc in group.running():
        if name != "llama":
            record_process(info, name, proc)
    if any(n == "backend" for n, _ in group.running()):
        info.backend_url = f"http://127.0.0.1:{settings.ports.backend}"
    write_launched(launched_path, info)


def cmd_start(args: argparse.Namespace) -> int:
    settings = _load_or_die(Path(args.settings))
    launched_path = Path(args.launched)
    root = REPO_ROOT
    base_url = f"http://127.0.0.1:{settings.ports.llama}"

    already_running_llama = wait_for_health(base_url, timeout=0.8, interval=0.2)
    group = ProcessGroup()
    stopping = threading.Event()
    llama_pid: int | None = None
    request, status = _restart_files(launched_path)
    request.unlink(missing_ok=True)

    try:
        if already_running_llama:
            banner(sys.stdout, "llama-server", f"reusing running instance on {base_url}")
            llama_pids = find_pids_by_port(settings.ports.llama)
            if llama_pids:
                llama_pid = llama_pids[0]
        elif args.no_llama:
            banner(sys.stdout, "llama-server", "not started (--no-llama)")
        else:
            llama_pid, error = _start_llama(group, settings, args, root)
            if error:
                logger.error("%s", error)
                return 1

        if args.no_backend:
            banner(sys.stdout, "backend", "not started (--no-backend)")
        else:
            try:
                _start_backend(group, settings, args, root, launched_path)
            except SpawnFailed as exc:
                logger.error("%s", exc)
                return 1

        # Frontend setup
        client_url = f"http://127.0.0.1:{settings.ports.client}"
        client_dir = root / "client"
        if args.no_frontend:
            banner(sys.stdout, "frontend", "not started (--no-frontend)")
        else:
            if not client_dir.is_dir():
                banner(sys.stdout, "frontend", f"not started (no {client_dir})")
                logger.error("client directory does not exist: %s", client_dir)
                return 1

            stale_frontend_pids = find_pids_by_port(settings.ports.client)
            if stale_frontend_pids:
                banner(sys.stdout, "frontend", f"clearing stale process on port {settings.ports.client}")
                for pid in stale_frontend_pids:
                    kill_pid_tree(pid)
                time.sleep(0.5)

            client_env = dict(os.environ)
            client_env["VITE_ATLAS_BACKEND_PORT"] = str(settings.ports.backend)
            try:
                group.spawn(
                    "frontend",
                    build_frontend_args(settings),
                    cwd=client_dir,
                    env=client_env,
                    ready_pattern=r"Local:\s+http://",
                    sink=sys.stdout,
                )
                logger.info("frontend starting on %s", client_url)
            except (SpawnFailed, FileNotFoundError) as exc:
                logger.error("%s", exc)
                return 1

        _record(launched_path, settings, group, llama_pid)
        _write_status(status, "ready", model=settings.model.name)

        if not group.children():
            banner(sys.stdout, "atlas", "nothing to supervise")
            logger.info("All requested services were disabled or managed externally.")
            return 0

        logger.info("Atlas is running. Press Ctrl+C or run 'atlas stop' to shut down.")

        def restart() -> None:
            nonlocal llama_pid, settings
            _restart(group, args, root, launched_path, own_llama=not already_running_llama)
            settings = load_settings(Path(args.settings))
            llama_pid = next((p.pid for n, p in group.running() if n == "llama"), None)

        _supervise(group, stopping, request, restart)
        return 0

    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl+C)...")
        return 0
    finally:
        stopping.set()
        # Orderly process tree termination
        group.close()

        # Port sweep safety check: guarantee ports are completely free on exit
        for label, port in [
            ("frontend", settings.ports.client),
            ("backend", settings.ports.backend),
            ("llama", settings.ports.llama),
        ]:
            if label == "llama" and already_running_llama:
                continue
            for pid in find_pids_by_port(port):
                kill_pid_tree(pid)

        launched_path.unlink(missing_ok=True)
        request.unlink(missing_ok=True)
        status.unlink(missing_ok=True)
        print("Atlas stopped cleanly.")


def _restart(group: ProcessGroup, args: argparse.Namespace, root: Path, launched_path: Path,
             *, own_llama: bool) -> None:
    """Restart llama-server and the backend with the settings now on disk.

    Asked for from the UI (Settings > Restart), so a model change or another
    restart setting applies without leaving the browser. The web UI keeps
    running and reconnects. The backend comes back even when llama-server
    fails, so the UI can say why and the user can pick another model.
    """
    _request, status = _restart_files(launched_path)
    _write_status(status, "restarting")
    try:
        settings = load_settings(Path(args.settings))
    except SettingsError as exc:
        _write_status(status, "failed", error=str(exc))
        return
    banner(sys.stdout, "atlas", f"restarting with model {settings.model.name!r}")
    group.stop("backend")
    error = None
    if own_llama and not args.no_llama:
        group.stop("llama")
        _pid, error = _start_llama(group, settings, args, root)
    elif not own_llama:
        error = "llama-server was not started by Atlas, so it was not restarted"
    if error:
        logger.error("%s", error)
    if not args.no_backend:
        try:
            _start_backend(group, settings, args, root, launched_path)
        except SpawnFailed as exc:
            error = error or str(exc)
    llama_pid = next((p.pid for n, p in group.running() if n == "llama"), None)
    _record(launched_path, settings, group, llama_pid)
    _write_status(status, "failed" if error else "ready", model=settings.model.name, error=error)


def _supervise(group: ProcessGroup, stopping: threading.Event, request: Path,
               restart: Callable[[], None]) -> None:
    while not stopping.is_set():
        if request.exists():
            request.unlink(missing_ok=True)
            restart()
        alive = group.running()
        if not alive:
            logger.warning("All child processes have stopped.")
            return
        time.sleep(0.5)


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop all running Atlas processes and verify ports are free."""
    path = Path(args.launched) if os.path.isabs(args.launched) else REPO_ROOT / args.launched
    settings_path = Path(args.settings) if os.path.isabs(args.settings) else REPO_ROOT / args.settings

    info = load_launched(path)
    try:
        settings = load_settings(settings_path)
    except Exception as exc:
        logger.debug("settings unavailable: %s", exc)
        settings = None

    stopped_any = False

    if info is not None and info.processes:
        print(f"Stopping launch {info.launch_id} (started {info.started_at})...")
        stopped, problems = stop_recorded(info)
        for name in stopped:
            print(f"  stopped {name}")
            stopped_any = True
        for problem in problems:
            print(f"  note: {problem}")

    if settings is not None:
        stopped_ports, problems_ports = stop_by_port(
            {
                "frontend": settings.ports.client,
                "backend": settings.ports.backend,
                "llama": settings.ports.llama,
            }
        )
        for name in stopped_ports:
            print(f"  stopped {name}")
            stopped_any = True
        for problem in problems_ports:
            print(f"  note: {problem}")

    path.unlink(missing_ok=True)

    if settings is not None:
        for label, port in [
            ("llama", settings.ports.llama),
            ("backend", settings.ports.backend),
            ("frontend", settings.ports.client),
        ]:
            remaining = find_pids_by_port(port)
            if remaining:
                print(f"  warning: port {port} ({label}) still held by PIDs: {remaining}")

    if stopped_any:
        print("Atlas stack stopped cleanly.")
    else:
        print("Nothing of ours was running.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="Atlas local agent")
    parser.add_argument("--settings", default=DEFAULT_SETTINGS, help="path to settings.json")
    parser.add_argument("--launched", default=DEFAULT_LAUNCHED, help="path to launched.json")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable verbose debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start llama-server, backend and frontend")
    start.add_argument("--no-llama", action="store_true", help="do not spawn llama-server")
    start.add_argument("--no-backend", action="store_true", help="do not spawn the backend")
    start.add_argument(
        "--no-frontend",
        "--no-client",
        dest="no_frontend",
        action="store_true",
        help="do not spawn the Vite frontend",
    )
    start.add_argument(
        "--health-timeout",
        type=float,
        default=180.0,
        help="seconds to wait for llama-server readiness",
    )
    start.set_defaults(func=cmd_start)

    stop = sub.add_parser("stop", help="stop all running Atlas processes")
    stop.set_defaults(func=cmd_stop)

    settings_cmd = sub.add_parser("settings", help="inspect settings.json")
    settings_sub = settings_cmd.add_subparsers(dest="settings_command", required=True)

    check = settings_sub.add_parser("check", help="validate settings.json")
    check.set_defaults(func=cmd_settings_check)

    show = settings_sub.add_parser("show", help="print resolved settings")
    show.add_argument("--restart-required", action="store_true")
    show.set_defaults(func=cmd_settings_show)

    return parser


def _install_signal_handlers() -> None:
    def _sig_handler(signum, frame):
        global _shutting_down
        if _shutting_down:
            sys.stderr.write("\nForce quitting...\n")
            sys.stderr.flush()
            os._exit(1)
        _shutting_down = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _sig_handler)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _install_signal_handlers()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())