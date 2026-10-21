"""The `atlas` command.

    atlas start [--dev] [--raw] [--no-llama] [--no-backend] [--no-client]
    atlas stop
    atlas status
    atlas logs [llama|backend|web] [-f] [-n N]
    atlas settings check | show [--restart-required]

`atlas start` shows the start screen in a terminal (`screen.py`), filtered
logs with a pinned status line with `--dev`, and plain lines when piped or
with `--raw` (`views.py`). The launcher does the work (`launcher.py`).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from agent.cli import launched as rec
from agent.cli.launch import build_llamacpp_args, describe_args
from agent.cli.launcher import SERVICES, Launcher, Options
from agent.cli.processes import kill_pid_tree
from agent.core import llama, paths
from agent.core.settings import Settings, SettingsError, load_settings


def _find_root() -> Path:
    """The project folder, so `atlas` works from any directory."""
    here = Path(__file__).resolve().parents[2]
    for candidate in (here, *Path.cwd().resolve().parents, Path.cwd().resolve()):
        if (candidate / "pyproject.toml").is_file() and (candidate / "agent").is_dir():
            return candidate
    return here


ROOT = _find_root()
LABELS = {"llama": "Model", "backend": "Backend", "web": "Web UI"}


def _settings(args: argparse.Namespace) -> Settings:
    try:
        return load_settings(Path(args.settings))
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


def _ago(ms: int) -> str:
    minutes = int((time.time() * 1000 - ms) / 60000)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def _print_status(info: rec.LaunchedInfo, alive: dict[str, dict]) -> None:
    started = time.strftime("%H:%M", time.localtime(info.started_at / 1000))
    print(f" Atlas  running since {started} ({_ago(info.started_at)}) · {info.mode} mode")
    for service in SERVICES:
        entry = alive.get(service)
        url = info.urls.get(service, "")
        if service == "llama" and info.model:
            url = info.model.get("name", "")
        if entry:
            print(f" ✓ {LABELS[service]:<9} PID {entry['pid']:<6} {url}".rstrip())
        elif service == "web" and info.urls.get("web"):
            print(f" ✓ {LABELS[service]:<9} {'':<10} {info.urls['web']}")
        else:
            print(f" · {LABELS[service]:<9} not running")


# ------------------------------------------------------------------ commands --


def cmd_start(args: argparse.Namespace) -> int:
    settings = _settings(args)
    launched_path = Path(args.launched)
    info = rec.load_launched(launched_path)
    alive = rec.running(info)
    if info and alive:
        _print_status(info, alive)
        print(" Atlas is already running. `atlas stop` stops it.")
        return 0

    options = Options(dev=args.dev, no_llama=args.no_llama, no_backend=args.no_backend,
                      no_client=args.no_client, health_timeout=args.health_timeout)
    launcher = Launcher(ROOT, Path(args.settings), launched_path, options, emit=lambda e: None)

    from agent.cli.views import DevView, PlainView

    if args.raw or not sys.stdout.isatty():
        view = PlainView(launcher, raw=args.raw)
    elif args.dev:
        view = DevView(launcher, raw=False)
    else:
        from agent.cli.screen import StartScreen

        view = StartScreen(launcher)
    launcher.emit = view.handle
    del settings
    return view.run()


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop the recorded processes, then anything of ours left on Atlas's ports."""
    launched_path = Path(args.launched)
    info = rec.load_launched(launched_path)
    # Removed first: a running start screen sees it gone and exits quietly,
    # instead of reporting each process it is about to lose as a crash.
    launched_path.unlink(missing_ok=True)
    stopped = 0
    for service in ("web", "backend", "llama"):
        entry = info.processes.get(service) if info else None
        if entry and rec.is_alive(entry):
            started = time.monotonic()
            kill_pid_tree(int(entry["pid"]))
            print(f" ✓ {LABELS[service]:<9} stopped (PID {entry['pid']}) in {time.monotonic() - started:.1f}s")
            stopped += 1
    try:
        s = load_settings(Path(args.settings))
        ports = {"backend": s.ports.backend, "llama": s.ports.llama, "web": s.ports.client}
        swept, problems = rec.stop_by_port(ports)
    except SettingsError:
        swept, problems = [], []
    for what in swept:
        print(f" ✓ stopped {what}")
    for problem in problems:
        print(f" ! {problem}")
    for name in ("launched.json", "restart.request", "restart.json"):
        launched_path.with_name(name).unlink(missing_ok=True)
    print(" Atlas stopped." if stopped or swept else " Atlas was not running.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    info = rec.load_launched(Path(args.launched))
    alive = rec.running(info)
    if not info or not alive:
        print(" Atlas is not running.")
        return 1
    _print_status(info, alive)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    settings = _settings(args)
    folder = paths.data_dir(settings) / "logs"
    services = [{"client": "web", "vite": "web"}.get(args.service, args.service)] if args.service else list(SERVICES)
    files = {s: folder / f"{s}.log" for s in services if (folder / f"{s}.log").exists()}
    if not files:
        print(f" No logs yet in {folder}.")
        return 1
    for service, path in files.items():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-args.lines:]
        prefix = f"{service:<8} " if len(files) > 1 else ""
        if len(files) > 1:
            print(f"── {service} ({path})")
        for line in lines:
            print(prefix + line)
    if not args.follow:
        return 0
    offsets = {s: p.stat().st_size for s, p in files.items()}
    try:
        while True:
            time.sleep(0.5)
            for service, path in files.items():
                size = path.stat().st_size if path.exists() else 0
                if size < offsets[service]:  # rotated by a new start
                    offsets[service] = 0
                if size > offsets[service]:
                    with path.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(offsets[service])
                        for line in fh.read().splitlines():
                            print((f"{service:<8} " if len(files) > 1 else "") + line, flush=True)
                    offsets[service] = size
    except KeyboardInterrupt:
        return 0


def cmd_settings_check(args: argparse.Namespace) -> int:
    settings = _settings(args)
    print(f"{args.settings}: OK")
    print(f"  models folder     = {paths.models_dir(settings)}")
    print(f"  model             = {settings.model.name}")
    print(f"  context_size      = {settings.model.context_size}")
    print(f"  ports             = llama {settings.ports.llama}, backend {settings.ports.backend}, "
          f"dev UI {settings.ports.client}")
    try:
        print(f"  llama-server args = {describe_args(build_llamacpp_args(settings))}")
    except llama.ModelError as exc:
        print(f"  model problem     = {exc}")
        return 1
    return 0


def cmd_settings_show(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not args.restart_required:
        print(json.dumps(settings.model_dump(mode="json"), indent=2))
        return 0
    changed = rec.restart_required(settings.model_dump(mode="json"), rec.load_launched(Path(args.launched)))
    print("restart required: " + ("yes" if changed else "no (settings match the running launch)"))
    for key, value in sorted(changed.items()):
        print(f"  {key} = {value!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas", description="Atlas, a local AI agent")
    parser.add_argument("--settings", default=str(ROOT / "settings.json"), help="path to settings.json")
    parser.add_argument("--launched", default=str(ROOT / "launched.json"), help="path to launched.json")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging from the CLI itself")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start the model, the backend and the web UI")
    start.add_argument("--dev", action="store_true", help="Vite with hot reload, filtered logs, pinned status line")
    start.add_argument("--raw", action="store_true", help="every line from every process, unfiltered")
    start.add_argument("--no-llama", action="store_true", help="do not start llama-server")
    start.add_argument("--no-backend", action="store_true", help="do not start the backend")
    start.add_argument("--no-client", "--no-frontend", dest="no_client", action="store_true",
                       help="do not start the web UI")
    start.add_argument("--health-timeout", type=float, default=180.0, help="seconds to wait for the model")
    start.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="stop everything Atlas started").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="what is running, on which ports, since when").set_defaults(func=cmd_status)

    logs = sub.add_parser("logs", help="show the log files")
    logs.add_argument("service", nargs="?", choices=[*SERVICES, "client", "vite"])
    logs.add_argument("-f", "--follow", action="store_true", help="keep printing new lines")
    logs.add_argument("-n", "--lines", type=int, default=40, help="lines to show (default 40)")
    logs.set_defaults(func=cmd_logs)

    settings_cmd = sub.add_parser("settings", help="inspect settings.json")
    settings_sub = settings_cmd.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("check", help="validate settings.json").set_defaults(func=cmd_settings_check)
    show = settings_sub.add_parser("show", help="print the resolved settings")
    show.add_argument("--restart-required", action="store_true")
    show.set_defaults(func=cmd_settings_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # The views own the terminal; only warnings (or -v) from the CLI's own code.
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
