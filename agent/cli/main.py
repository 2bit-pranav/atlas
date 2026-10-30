"""The `atlas` command.

    atlas start [--dev] [--raw] [--no-llama] [--no-backend] [--no-client]
    atlas stop
    atlas status
    atlas logs [llama|backend|web] [-f] [-n N]
    atlas settings check | show [--restart-required]

`atlas start` shows the start screen in a terminal (`screen.py`), filtered
logs with a pinned status line with `--dev`, and plain lines when piped or
with `--raw` (`views/`). The launcher does the work (`launcher/supervisor.py`);
the commands are in `commands.py`.
"""


from __future__ import annotations

import argparse
import logging
import sys

from agent.cli.commands import (
    ROOT,
    cmd_logs,
    cmd_settings_check,
    cmd_settings_show,
    cmd_start,
    cmd_status,
    cmd_stop,
)
from agent.cli.launcher.supervisor import SERVICES


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
