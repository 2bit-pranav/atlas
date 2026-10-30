"""`--dev`: filtered logs from every service, with a pinned status line."""


from __future__ import annotations

import time

from rich.console import Console
from rich.live import Live
from rich.text import Text

from agent.cli.launcher.logs import Line, LogFilter
from agent.cli.launcher.supervisor import SERVICES, Event, Launcher
from agent.cli.views.base import COLOURS, SPINNER, _Base


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
        self.count_run(e)
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


__all__ = ["DevView"]
