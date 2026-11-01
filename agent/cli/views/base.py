"""What the views of `atlas start` share. The start screen is `screen.py`.

* `PlainView`: one line per event, no colour or cursor movement. Used when
  stdout is not a terminal (piped, redirected, CI) and with `--raw`, where it
  also prints every line every process writes.
* `DevView` (`--dev`): filtered, single-line logs scrolling in the terminal's
  own scrollback, so tracebacks can be scrolled, searched and copied, with one
  status line pinned below them.
"""


from __future__ import annotations

import re
import threading
import time
from typing import Any

from agent.cli.launcher.supervisor import Event, Launcher

LABELS = {"llama": "Model", "backend": "Backend", "web": "Web UI"}


COLOURS = {"llama": "magenta", "backend": "cyan", "web": "green"}


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


_RUN = re.compile(r"\brun (\w+) (?:completed|failed|cancelled|interrupted)\b")


def ready_text(e: Event) -> str:
    """What a service's row says once it is ready."""
    d = e.details
    if e.service == "llama":
        parts = [str(d.get("name", ""))]
        if d.get("ctx"):
            parts.append(f"{int(d['ctx']) // 1024}k ctx")
        if d.get("vision"):
            parts.append("vision")
        parts.append("GPU" if d.get("gpu") else "CPU")
        return " · ".join(parts)
    if e.service == "backend":
        return str(d.get("url", "")).removeprefix("http://")
    return str(d.get("url", ""))


def duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m" if minutes else f"{int(seconds)}s"


class _Base:
    """Runs the launcher for a view; the view only says how events look."""

    def __init__(self, launcher: Launcher) -> None:
        self.launcher = launcher
        self.runs: set[str] = set()
        self._done = threading.Event()

    def handle(self, event: Event) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        """Called a few times a second from the main thread."""

    def run(self) -> int:
        launcher = self.launcher
        ok = launcher.start()
        self.started(ok)
        if not ok and self.exit_on_failure:
            launcher.stop()
            return 1
        threading.Thread(target=launcher.supervise, daemon=True).start()
        try:
            while not self._done.wait(0.25) and not launcher.ended.is_set():
                self.tick()
        except KeyboardInterrupt:
            pass
        launcher.stop()
        self.stopped()
        return 0

    exit_on_failure = True

    def started(self, ok: bool) -> None:
        pass

    def stopped(self) -> None:
        pass

    def count_run(self, e: Event) -> None:
        """A finished run, from the backend's own summary line (no polling)."""
        if e.kind == "log_line" and e.service == "backend" and (m := _RUN.search(e.text)):
            self.runs.add(m.group(1))

    def _poll_runs(self) -> None:
        """The run in progress, for a view that shows it (the start screen)."""
        while not self._done.wait(2.0):
            self.on_run(self.launcher.active_run())

    def on_run(self, run: dict[str, Any] | None) -> None:
        pass

    def summary(self) -> str:
        up = duration(time.time() - self.launcher.started_at)
        runs = len(self.runs)
        return f"Atlas stopped cleanly · up {up} · {runs} run{'s' * (runs != 1)}"


__all__ = ["COLOURS", "LABELS", "SPINNER", "duration", "ready_text"]
