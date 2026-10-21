"""The plain and dev views of `atlas start`. The start screen is `screen.py`.

* `PlainView`: one line per event, no colour or cursor movement. Used when
  stdout is not a terminal (piped, redirected, CI) and with `--raw`, where it
  also prints every line every process writes.
* `DevView` (`--dev`): filtered, single-line logs scrolling in the terminal's
  own scrollback, so tracebacks can be scrolled, searched and copied, with one
  status line pinned below them.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.text import Text

from agent.cli.launcher import SERVICES, Event, Launcher
from agent.cli.log_filters import Line, LogFilter

LABELS = {"llama": "Model", "backend": "Backend", "web": "Web UI"}
COLOURS = {"llama": "magenta", "backend": "cyan", "web": "green"}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


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
        threading.Thread(target=self._poll_runs, daemon=True).start()
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

    def _poll_runs(self) -> None:
        while not self._done.wait(2.0):
            run = self.launcher.active_run()
            if run and run.get("id"):
                self.runs.add(run["id"])
            self.on_run(run)

    def on_run(self, run: dict[str, Any] | None) -> None:
        pass

    def summary(self) -> str:
        up = duration(time.time() - self.launcher.started_at)
        runs = len(self.runs)
        return f"Atlas stopped cleanly · up {up} · {runs} run{'s' * (runs != 1)}"


class PlainView(_Base):
    def __init__(self, launcher: Launcher, *, raw: bool) -> None:
        super().__init__(launcher)
        self.raw = raw
        self.filter = LogFilter()
        self._lock = threading.Lock()

    def _print(self, service: str, text: str) -> None:
        with self._lock:
            print(f"{time.strftime('%H:%M:%S')} {service:<8} {text}", flush=True)

    def handle(self, e: Event) -> None:
        if e.kind == "log_line":
            if self.raw:
                self._print(e.service, e.raw)
            else:
                for line in self.filter.feed(e.service, e.level, e.text):
                    self._line(line)
        elif e.kind == "starting":
            self._print(e.service, f"starting  {e.text}".rstrip())
        elif e.kind == "ready":
            self._print(e.service, f"ready in {e.seconds or 0:.1f}s  {ready_text(e)}")
        elif e.kind == "failed":
            self._print(e.service, f"failed: {e.text}")
            for extra in [e.hint, f"log: {e.log}", *e.lines]:
                if extra:
                    self._print(e.service, f"  {extra}")
        elif e.kind in ("stopping", "stopped") and e.text:
            self._print(e.service, e.text)

    def _line(self, line: Line) -> None:
        self._print(line.service, f"{line.level or ' '} {line.text}")

    def tick(self) -> None:
        if not self.raw:
            for line in self.filter.flush():
                self._line(line)

    def started(self, ok: bool) -> None:
        urls = self.launcher.info.urls
        if ok:
            self._print("atlas", f"ready · {urls.get('web') or urls.get('backend') or ''}".rstrip(" ·"))
        else:
            self._print("atlas", "failed to start; stopping")

    def stopped(self) -> None:
        print(self.summary(), flush=True)


class DevView(_Base):
    exit_on_failure = False  # keep the others running, and their logs, to debug the failure

    def __init__(self, launcher: Launcher, *, raw: bool) -> None:
        super().__init__(launcher)
        self.raw = raw
        self.filter = LogFilter(raw=raw)
        self.console = Console(highlight=False)
        self.rows: dict[str, tuple[str, float | None, float]] = {}  # service -> (state, seconds, since)
        self.live = Live(self._status(), console=self.console, refresh_per_second=8, transient=True)

    def run(self) -> int:
        with self.live:
            return super().run()

    def _status(self) -> Text:
        text = Text(" Atlas dev ", style="bold")
        for service in SERVICES:
            state, seconds, since = self.rows.get(service, ("waiting", None, time.time()))
            name = "vite" if service == "web" else service
            text.append(f" {name} ", style=COLOURS[service])
            if state == "ready":
                text.append(f"✓ {seconds or 0:.1f}s", style="green")
            elif state == "failed":
                text.append("✗", style="red")
            elif state == "starting":
                text.append(SPINNER[int(time.time() * 10) % len(SPINNER)] + f" {time.time() - since:.0f}s", style="yellow")
            else:
                text.append("·", style="dim")
            text.append(" ")
        urls = self.launcher.info.urls
        if url := urls.get("web") or urls.get("backend"):
            text.append(f"  {url}", style="bold")
        return text

    def _emit_line(self, line: Line) -> None:
        text = Text()
        text.append(time.strftime("%H:%M:%S", time.localtime(line.at)) + " ", style="dim")
        name = "vite" if line.service == "web" else line.service
        text.append(f"{name:<8}", style=COLOURS.get(line.service, ""))
        text.append(f" {line.level or ' '}  ", style={"W": "yellow", "E": "red"}.get(line.level, ""))
        text.append(line.text, style="red" if line.level == "E" else "")
        # Tracebacks wrap: cutting one is worse than a long screen.
        if line.traceback or self.raw:
            self.console.print(text, soft_wrap=False)
        else:
            self.console.print(text, no_wrap=True, overflow="ellipsis")

    def handle(self, e: Event) -> None:
        if e.kind == "log_line":
            for line in self.filter.feed(e.service, e.level, e.text):
                self._emit_line(line)
        elif e.kind == "starting":
            self.rows[e.service] = ("starting", None, time.time())
        elif e.kind == "ready":
            self.rows[e.service] = ("ready", e.seconds, time.time())
            if e.service == "web" and e.details.get("stale"):
                self._emit_line(Line("web", "W", "the built UI is older than its sources: run `npm run build`"))
        elif e.kind == "failed":
            self.rows[e.service] = ("failed", None, time.time())
            self._emit_line(Line(e.service, "E", f"{e.text}. {e.hint}".strip()))
            for raw in e.lines:
                self._emit_line(Line(e.service, "E", raw, traceback=True))
            self._emit_line(Line(e.service, "E", f"log: {e.log}"))
        elif e.kind == "stopping":
            self.rows[e.service] = ("starting", None, time.time())
        elif e.kind == "stopped":
            self.rows[e.service] = ("stopped", None, time.time())

    def tick(self) -> None:
        for line in self.filter.flush():
            self._emit_line(line)
        self.live.update(self._status())

    def stopped(self) -> None:
        self.live.stop()
        self.console.print(self.summary())


__all__ = ["DevView", "LABELS", "PlainView", "SPINNER", "duration", "ready_text"]
