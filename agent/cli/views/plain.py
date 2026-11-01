"""Plain lines, one per event: for a pipe, a log file, or `--raw`."""


from __future__ import annotations

import threading
import time

from agent.cli.launcher.logs import Line, LogFilter
from agent.cli.launcher.supervisor import Event, Launcher
from agent.cli.views.base import _Base, ready_text


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
        self.count_run(e)
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


__all__ = ["PlainView"]
