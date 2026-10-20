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

import httpx

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
from agent.core import llama as router, paths
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
    print(f"  default model     = {settings.model.name}")
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


def cmd_start(args: argparse.Namespace) -> int:
    settings = _load_or_die(Path(args.settings))
    launched_path = Path(args.launched)
    root = REPO_ROOT

    llama_args = build_llamacpp_args(settings)
    base_url = f"http://127.0.0.1:{settings.ports.llama}"

    already_running_llama = wait_for_health(base_url, timeout=0.8, interval=0.2)
    group = ProcessGroup()
    stopping = threading.Event()
    llama_pid: int | None = None

    try:
        if already_running_llama and not router.is_router(base_url):
            logger.error("a llama-server on %s is not in router mode (started by an older Atlas, or by hand). "
                         "Run `atlas stop`, then `atlas start`.", base_url)
            return 1
        if already_running_llama:
            banner(sys.stdout, "llama-server", f"reusing running instance on {base_url}")
            llama_pids = find_pids_by_port(settings.ports.llama)
            if llama_pids:
                llama_pid = llama_pids[0]
        elif args.no_llama:
            banner(sys.stdout, "llama-server", "not started (--no-llama)")
        else:
            started = time.monotonic()
            llama, relay = group.spawn(
                "llama",
                llama_args,
                cwd=root,
                ready_pattern=r"listening on ",
                sink=sys.stdout,
            )
            llama_pid = llama.pid
            logger.info("waiting for llama-server to start (up to %.0fs)...", args.health_timeout)

            ok, reason = wait_until_ready(llama, relay, base_url, timeout=args.health_timeout)
            if not ok:
                logger.error("llama-server did not start: %s", reason)
                tail = relay.tail_text()
                if tail:
                    logger.error("last output from llama-server:\n%s", tail)
                return 1

            logger.info("llama-server ready in %.1fs (%s)", time.monotonic() - started, reason)

        # The router is up with nothing loaded: load the default model now, so
        # the first message does not also wait for it.
        default_model: dict = {}
        if not args.no_llama or already_running_llama:
            name = settings.model.name
            logger.info("loading model %r (up to %.0fs)...", name, args.health_timeout)
            started = time.monotonic()
            try:
                default_model = router.load(base_url, name, timeout=args.health_timeout)
            except (router.ModelError, httpx.HTTPError) as exc:
                logger.error("%s", exc)
                logger.error("set model.name to a subfolder of %s (Settings > Model & server)",
                             paths.models_dir(settings))
                return 1
            logger.info("model %r ready in %.1fs", name, time.monotonic() - started)
        model_file, mmproj_file = router.files(default_model) if default_model else (None, None)

        # Baseline launched.json record
        info = build_launched_info(
            llama_base_url=base_url,
            llama_args=llama_args,
            settings_dict=settings.model_dump(mode="json"),
            model_path=model_file,
            mmproj_path=mmproj_file,
            previous=load_launched(launched_path),
            llama_pid=llama_pid,
        )
        if llama_pid:
            record_process(info, "llama", llama_pid)
        write_launched(launched_path, info)

        # Backend setup
        backend_url = f"http://127.0.0.1:{settings.ports.backend}"
        if args.no_backend:
            banner(sys.stdout, "backend", "not started (--no-backend)")
        else:
            # Clean up stale backend if port 8000 is occupied
            stale_backend_pids = find_pids_by_port(settings.ports.backend)
            if stale_backend_pids:
                banner(sys.stdout, "backend", f"clearing stale process on port {settings.ports.backend}")
                for pid in stale_backend_pids:
                    kill_pid_tree(pid)
                time.sleep(0.5)

            try:
                backend_env = dict(os.environ)
                backend_env["ATLAS_SETTINGS"] = str(Path(args.settings).resolve())
                backend_env["ATLAS_ROOT"] = str(root)
                backend_env["PYTHONUTF8"] = "1"
                backend_env["PYTHONIOENCODING"] = "utf-8"
                backend, _ = group.spawn(
                    "backend",
                    build_backend_args(settings),
                    cwd=root,
                    env=backend_env,
                    sink=sys.stdout,
                )
                record_process(info, "backend", backend)
                info.backend_url = backend_url
                logger.info("backend starting on %s", backend_url)
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
                frontend, _ = group.spawn(
                    "frontend",
                    build_frontend_args(settings),
                    cwd=client_dir,
                    env=client_env,
                    ready_pattern=r"Local:\s+http://",
                    sink=sys.stdout,
                )
                record_process(info, "frontend", frontend)
                logger.info("frontend starting on %s", client_url)
            except (SpawnFailed, FileNotFoundError) as exc:
                logger.error("%s", exc)
                return 1

        write_launched(launched_path, info)

        if not group.children():
            banner(sys.stdout, "atlas", "nothing to supervise")
            logger.info("All requested services were disabled or managed externally.")
            return 0

        logger.info("Atlas is running. Press Ctrl+C or run 'atlas stop' to shut down.")
        _supervise(group, stopping)
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
        print("Atlas stopped cleanly.")


def _supervise(group: ProcessGroup, stopping: threading.Event) -> None:
    while not stopping.is_set():
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