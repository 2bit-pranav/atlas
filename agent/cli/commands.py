"""The `atlas` commands: start, stop, status, logs, settings check/show."""


from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agent.cli import launched as rec
from agent.cli.launcher.services import build_llamacpp_args, describe_args
from agent.cli.launcher.supervisor import SERVICES, Launcher, Options
from agent.cli.ports import stop_by_port
from agent.cli.procs import kill_pid_tree
from agent.config import paths
from agent.config.settings import Settings, SettingsError, load_settings
from agent.model import server as llama


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

    from agent.cli.views.dev import DevView
    from agent.cli.views.plain import PlainView

    if args.raw or not sys.stdout.isatty():
        view = PlainView(launcher, raw=args.raw)
    elif args.dev:
        view = DevView(launcher, raw=False)
    else:
        from agent.cli.views.screen import StartScreen

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
        swept, problems = stop_by_port(ports)
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
