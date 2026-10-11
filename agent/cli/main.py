"""``atlas`` command line (spec section 3, L1).

    atlas up            start llama-server, the backend and the client
    atlas down          stop whatever this CLI started
    atlas settings check    validate settings.json
    atlas settings show     print resolved settings, and what needs a restart

``up`` is deliberately the only command that supervises processes. It writes
``launched.json`` with the launch id, the llama.cpp build and the GGUF hash, so
the backend can compare the file against what is actually running and report
"restart required" (section 4).
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from agent.cli.launch import build_backend_args, build_llamacpp_args, describe_args
from agent.cli.launched import (
    build_launched_info,
    load_launched,
    record_process,
    restart_required,
    stop_by_port,
    stop_recorded,
    wait_for_health,
    wait_until_ready,
    write_launched,
)
from agent.cli.processes import ProcessGroup, SpawnFailed, banner
from agent.cli.settings import Settings, SettingsError, load_settings

logger = logging.getLogger("atlas")

DEFAULT_SETTINGS = "settings.json"
DEFAULT_LAUNCHED = "launched.json"


# ------------------------------------------------------------------- helpers --


def _load_or_die(path: Path) -> Settings:
    try:
        return load_settings(path)
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


def _backend_available() -> bool:
    """The FastAPI app lands in L2/L3; before that, `atlas up` is llama-only."""
    import importlib.util

    try:
        return importlib.util.find_spec("agent.server.main") is not None
    except (ImportError, ValueError):
        return False


def _print_restart_status(settings: Settings, launched_path: Path) -> list[str]:
    """Compare the file against what is running. Returns the changed keys."""
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
    print(f"  model.path        = {settings.model.path}")
    print(f"  context_size      = {settings.model.context_size}")
    print(f"  parallel_slots    = {settings.model.parallel_slots}")
    print(f"  llama port        = {settings.ports.llama}")
    print(f"  llama-server args = {describe_args(build_llamacpp_args(settings))}")
    return 0


def cmd_settings_show(args: argparse.Namespace) -> int:
    settings = _load_or_die(Path(args.settings))
    if args.restart_required:
        _print_restart_status(settings, Path(args.launched))
        return 0
    print(json.dumps(settings.model_dump(mode="json"), indent=2))
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    settings = _load_or_die(Path(args.settings))
    launched_path = Path(args.launched)

    llama_args = build_llamacpp_args(settings)
    base_url = f"http://127.0.0.1:{settings.ports.llama}"

    # Always probe, even with --no-llama: that flag means "do not spawn", not
    # "do not look". Skipping the probe made the warning claim nothing was
    # running when a perfectly good server was answering.
    already_running = wait_for_health(base_url, timeout=0.8, interval=0.2)
    if already_running:
        if args.no_llama:
            banner(sys.stdout, "llama-server", f"using the one already on {base_url}")
            logger.info("--no-llama: attaching to the running server on %s", base_url)
        else:
            banner(sys.stdout, "llama-server", f"reusing the one already on {base_url}")
            logger.warning(
                "reusing the running llama-server; it was not started here, so it "
                "will not be stopped when this CLI exits. Run `atlas down` to stop it."
            )
    elif args.no_llama:
        banner(sys.stdout, "llama-server", "not started (--no-llama)")
        logger.warning("nothing is answering on %s", base_url)

    group = ProcessGroup()
    stopping = threading.Event()
    llama_pid = None

    try:
        if not already_running and not args.no_llama:
            started = time.monotonic()
            llama, relay = group.spawn(
                "llama", llama_args, ready_pattern=r"listening on ", sink=sys.stdout
            )
            llama_pid = llama.pid
            logger.info(
                "waiting for llama-server to load the model (up to %.0fs)...",
                args.health_timeout,
            )

            ok, reason = wait_until_ready(llama, relay, base_url, timeout=args.health_timeout)
            if not ok:
                logger.error("llama-server did not start: %s", reason)
                tail = relay.tail_text()
                if tail:
                    logger.error("last output from llama-server:\n%s", tail)
                return 1

            logger.info(
                "llama-server ready in %.1fs (%s)", time.monotonic() - started, reason
            )

        # launched.json: the backend compares against this to detect drift.
        info = build_launched_info(
            llama_base_url=base_url,
            llama_args=llama_args,
            settings_dict=settings.model_dump(mode="json"),
            model_path=settings.model.path or None,
            mmproj_path=settings.model.mmproj_path,
            previous=load_launched(launched_path),
            llama_pid=llama_pid,
        )
        write_launched(launched_path, info)
        logger.info(
            "launch %s recorded (build %s, model %s)",
            info.launch_id,
            info.llamacpp_build or "unknown",
            info.model_sha256 or "unhashed",
        )
        if not already_running and not args.no_llama:
            # Record the pid only now that `info` exists, so `atlas down` in
            # another terminal can find this llama-server.
            record_process(info, "llama", llama)

        start_backend = not args.no_backend
        backend_url = f"http://127.0.0.1:{settings.ports.backend}"
        if start_backend and wait_for_health(backend_url, timeout=1.0, interval=0.3):
            banner(sys.stdout, "backend", "already running - not starting a second one")
            logger.warning(
                "a backend is already answering on %s. Run `atlas down` first if you "
                "want this launch to own it.", backend_url
            )
            start_backend = False
        elif start_backend and not _backend_available():
            banner(sys.stdout, "backend", "not started (not implemented yet)")
            logger.warning(
                "agent.server.main does not exist yet (it arrives in L2/L3); "
                "running llama-server only. Pass --no-backend to silence this."
            )
            start_backend = False

        if not start_backend:
            pass
        else:
            try:
                backend, _ = group.spawn("backend", build_backend_args(settings), sink=sys.stdout)
            except SpawnFailed as exc:
                logger.error("%s", exc)
                return 1
            record_process(info, "backend", backend)
            info.backend_url = backend_url
            logger.info("backend starting on %s", backend_url)

        # Rewrite launched.json so it carries the backend pid as well.
        write_launched(launched_path, info)

        if not group.children():
            banner(sys.stdout, "atlas", "nothing to supervise")
            logger.info(
                "Everything was already running, so this launch started no processes "
                "and has nothing to supervise. Run `atlas down` first if you want this "
                "terminal to own the stack."
            )
            return 0

        logger.info("Atlas is up. Ctrl+C to stop everything.")
        _supervise(group, stopping)
        return 0

    except KeyboardInterrupt:
        logger.info("interrupted; shutting down")
        return 0
    finally:
        stopping.set()
        group.close()


def _supervise(group: ProcessGroup, stopping: threading.Event) -> None:
    """Block until interrupted or until a supervised process exits on its own."""
    while not stopping.is_set():
        alive = group.running()
        if not alive:
            logger.warning("every child process has exited")
            return
        time.sleep(0.5)


# ------------------------------------------------------------------ entrypoint --


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="Atlas on Strands")
    parser.add_argument("--settings", default=DEFAULT_SETTINGS)
    parser.add_argument("--launched", default=DEFAULT_LAUNCHED)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="start the stack")
    up.add_argument("--no-llama", action="store_true", help="do not spawn llama-server")
    up.add_argument("--no-backend", action="store_true", help="do not spawn the backend")
    up.add_argument("--health-timeout", type=float, default=180.0)
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="stop the running stack")
    down.set_defaults(func=cmd_down)

    restart = sub.add_parser(
        "restart", help="stop the running stack, then start it here"
    )
    restart.add_argument("--no-llama", action="store_true")
    restart.add_argument("--no-backend", action="store_true")
    restart.set_defaults(func=cmd_restart)

    settings_cmd = sub.add_parser("settings", help="inspect settings.json")
    settings_sub = settings_cmd.add_subparsers(dest="settings_command", required=True)

    check = settings_sub.add_parser("check", help="validate settings.json")
    check.set_defaults(func=cmd_settings_check)

    show = settings_sub.add_parser("show", help="print resolved settings")
    show.add_argument("--restart-required", action="store_true")
    show.set_defaults(func=cmd_settings_show)

    db_cmd = sub.add_parser("db", help="the app database")
    db_cmd.add_argument("--db", default=None, help="path (default: <data dir>/atlas.db)")
    db_sub = db_cmd.add_subparsers(dest="db_command", required=True)

    db_init = db_sub.add_parser("init", help="create or upgrade the schema")
    db_init.set_defaults(func=cmd_db_init)

    db_info = db_sub.add_parser("info", help="summarise contents")
    db_info.set_defaults(func=cmd_db_info)


    return parser


def cmd_down(args: argparse.Namespace) -> int:
    """Stop the running stack, even from a terminal that did not start it.

    Primary path: the pids recorded in ``launched.json``, each carrying its
    creation time. A pid can be recycled, so identity is verified before
    anything is terminated. Fallback: find the stack by its listening ports and
    confirm the process looks like ours before touching it.
    """
    path = Path(args.launched)
    info = load_launched(path)

    settings = None
    try:
        settings = load_settings(Path(args.settings))
    except SettingsError as exc:
        logger.debug("settings unavailable for the port fallback: %s", exc)

    if info is None or not info.processes:
        print(f"no usable {path}; falling back to the configured ports.")
        if settings is not None:
            stopped, problems = stop_by_port(
                {"llama": settings.ports.llama, "backend": settings.ports.backend}
            )
            for name in stopped:
                print(f"  stopped {name}")
            for problem in problems:
                print(f"  note: {problem}")
            if stopped:
                path.unlink(missing_ok=True)
                return 0
        print("Nothing of ours is running.")
        return 0

    print(f"stopping launch {info.launch_id} (started {info.started_at})")
    stopped, problems = stop_recorded(info)

    for name in stopped:
        print(f"  stopped {name}")
    for problem in problems:
        print(f"  note: {problem}")

    path.unlink(missing_ok=True)
    print(f"removed {path}")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """Stop the running stack, then start it again in this terminal."""
    stop_args = argparse.Namespace(launched=args.launched, settings=args.settings)
    cmd_down(stop_args)
    up_args = argparse.Namespace(
        settings=args.settings, launched=args.launched, no_llama=args.no_llama,
        no_backend=args.no_backend, health_timeout=180.0, verbose=args.verbose,
    )
    return cmd_up(up_args)


def cmd_db_init(args: argparse.Namespace) -> int:
    """Create or upgrade the app database (idempotent)."""
    from agent.core import open_repo, resolve_data_dir
    from agent.core.migrations import current_version, pending

    db_path = Path(args.db) if args.db else resolve_data_dir() / "atlas.db"
    repo = open_repo(db_path)
    try:
        version = current_version(repo.db.connection)
        todo = pending(repo.db.connection)
        print(f"{db_path}")
        print(f"  schema version : {version}")
        print(f"  pending        : {len(todo)}")
        for number, name, _ in todo:
            print(f"    - {number} {name}")
    finally:
        repo.db.close()
    return 0


def cmd_db_info(args: argparse.Namespace) -> int:
    """Summarise what is in the database right now."""
    from agent.core import open_repo, resolve_data_dir

    db_path = Path(args.db) if args.db else resolve_data_dir() / "atlas.db"
    if not db_path.exists():
        print(f"no database at {db_path}; run `atlas db init`")
        return 1
    repo = open_repo(db_path)
    try:
        conn = repo.db.connection
        print(f"{db_path}")
        chats = conn.execute("SELECT COUNT(*) c FROM chats").fetchone()["c"]
        nodes = conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
        runs = conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
        events = conn.execute("SELECT COUNT(*) c FROM run_events").fetchone()["c"]
        print(f"  chats   : {chats}")
        print(f"  nodes   : {nodes}")
        print(f"  runs    : {runs}")
        print(f"  events  : {events}")
        active = repo.active_run()
        print(f"  active  : {active.id} ({active.status})" if active else "  active  : none")
    finally:
        repo.db.close()
    return 0


def _install_signal_handlers() -> None:
    """Make Ctrl+C *and* Ctrl+Break unwind through the normal shutdown path.

    On Windows, Ctrl+Break arrives as SIGBREAK, which Python does not turn into
    KeyboardInterrupt; without this the process dies with
    STATUS_CONTROL_C_EXIT. The Job Object would still clean up the children, but
    the exit status and the log output would be wrong for a supervised launch.
    """
    if not hasattr(signal, "SIGBREAK"):
        return

    def _on_break(signum, frame):  # noqa: ANN001, ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGBREAK, _on_break)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs one line per request at INFO. Our health polling is expected to
    # miss while the model loads, and those "misses" were filling the terminal
    # with connection errors that told the user nothing.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _install_signal_handlers()
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
