"""The start screen: `atlas start` in a terminal.

A small panel drawn inline below the prompt (Rich Live, never full screen;
Textual's inline mode does not exist on Windows), about eight lines tall:

     Atlas                                        ready in 12.8s
     ─────────────────────────────────────────────────────────────
     ✓ Model     gemma · 32k ctx · vision · GPU                12.8s
     ✓ Backend   127.0.0.1:8000                                 1.2s
     ✓ Web UI    http://127.0.0.1:8000                          0.0s
     ─────────────────────────────────────────────────────────────
     o open UI   l logs   r restart   q stop

It stays as a live status panel. A failed row says what happened, what to
do and where the log is; `l` opens the filtered logs under the rows. On exit
it leaves a single line in the scrollback.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import webbrowser
from collections import deque
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from agent.cli.launcher import SERVICES, Event, Launcher
from agent.cli.log_filters import Line, LogFilter
from agent.cli.views import COLOURS, LABELS, SPINNER, _Base, ready_text

WIDTH = 66
LOG_LINES = 15


class _Keys:
    """Single key presses without Enter, on Windows and POSIX terminals."""

    def __init__(self) -> None:
        self.queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._restore: Any = None

    def start(self) -> None:
        if sys.platform != "win32":
            import termios
            import tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)  # keeps ISIG, so Ctrl+C still interrupts
            self._restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        if sys.platform == "win32":
            import msvcrt

            while not self._stop.wait(0.05):
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\x00", "\xe0"):  # arrows and function keys: two codes
                        code = msvcrt.getwch()
                        ch = {"K": "left", "M": "right"}.get(code, "")
                    self.queue.put({"\t": "right", "\x1b": "esc", "\x03": "q"}.get(ch, ch.lower()))
        else:
            import select

            while not self._stop.is_set():
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if ready:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":  # Esc, or the start of an arrow key
                        more, _, _ = select.select([sys.stdin], [], [], 0.02)
                        if more and sys.stdin.read(1) == "[":
                            ch = {"D": "left", "C": "right"}.get(sys.stdin.read(1), "")
                        else:
                            ch = "esc"
                    self.queue.put({"\t": "right"}.get(ch, ch.lower()))

    def stop(self) -> None:
        self._stop.set()
        if self._restore:
            self._restore()


class StartScreen(_Base):
    exit_on_failure = False  # the screen stays: r retries, q quits

    def __init__(self, launcher: Launcher) -> None:
        super().__init__(launcher)
        self.console = Console(highlight=False)
        self.rows: dict[str, dict[str, Any]] = {s: {"state": "waiting"} for s in SERVICES}
        self.filter = LogFilter()
        self.logs: dict[str, deque[Line]] = {s: deque(maxlen=200) for s in SERVICES}
        self.show_logs = False
        self.tab = 0
        self.run_line = ""
        self.header = "starting…"
        self.ready_in: float | None = None
        self.keys = _Keys()
        self._quit = threading.Event()
        self._busy = threading.Lock()  # one start/restart at a time

    # --------------------------------------------------------------- events --

    def handle(self, e: Event) -> None:
        row = self.rows[e.service]
        self.count_run(e)
        if e.kind == "log_line":
            for line in self.filter.feed(e.service, e.level, e.text):
                self.logs[line.service].append(line)
        elif e.kind == "starting":
            if row.get("state") != "starting":
                row["since"] = time.time()
            row.update(state="starting", text=e.text, hint="", log="")
        elif e.kind == "ready":
            row.update(state="ready", text=ready_text(e), seconds=e.seconds,
                       note="older than its sources: `npm run build`, or use --dev" if e.details.get("stale") else "")
        elif e.kind == "failed":
            row.update(state="failed", text=e.text, hint=e.hint, log=e.log, lines=e.lines)
            for raw in e.lines:
                self.logs[e.service].append(Line(e.service, "E", raw, traceback=True))
        elif e.kind == "stopping":
            row.update(state="stopping", since=time.time())
        elif e.kind == "stopped":
            row.update(state="idle", text=e.text or "stopped", hint="", note="")
        self._update_header()

    def _update_header(self) -> None:
        states = [r["state"] for s, r in self.rows.items() if r["state"] not in ("idle",)]
        if self._quit.is_set():
            self.header = "stopping…"
        elif any(s in ("starting", "stopping", "waiting") for s in states):
            self.header = "starting…"
        elif any(s == "failed" for s in states):
            self.header = "failed"
        elif states:
            if self.ready_in is None:
                self.ready_in = time.time() - self.launcher.started_at
            self.header = f"ready in {self.ready_in:.1f}s"

    def on_run(self, run: dict[str, Any] | None) -> None:
        if not run:
            self.run_line = ""
            return
        parts = ["running"]
        if run.get("chat_title"):
            parts.append(f"chat “{run['chat_title']}”")
        if run.get("tokens_per_second"):
            parts.append(f"{run['tokens_per_second']:.0f} tok/s")
        self.run_line = " · ".join(parts)

    # --------------------------------------------------------------- render --

    def render(self) -> Group:
        width = min(WIDTH, self.console.width - 1)
        rule = Text(" " + "─" * (width - 1), style="dim")
        head = Table.grid(expand=False, padding=0)
        head.add_column(width=width - 20)
        head.add_column(width=20, justify="right")
        style = {"failed": "red", "starting…": "yellow", "stopping…": "yellow"}.get(self.header, "green")
        head.add_row(Text(" Atlas", style="bold"), Text(self.header, style=style))

        rows = Table.grid(padding=(0, 1))
        rows.add_column(width=2)
        rows.add_column(width=8)
        text_width = width - 22
        rows.add_column(width=text_width)  # failures wrap; everything else is cut to one line
        rows.add_column(width=7, justify="right")
        frame = SPINNER[int(time.time() * 10) % len(SPINNER)]
        for service in SERVICES:
            r = self.rows[service]
            state = r["state"]
            icon = {"ready": Text(" ✓", "green"), "failed": Text(" ✗", "red"), "idle": Text(" ·", "dim"),
                    "waiting": Text(" ·", "dim")}.get(state, Text(" " + frame, "yellow"))
            if state in ("starting", "stopping"):
                timer = f"{time.time() - r.get('since', time.time()):.1f}s"
                text = Text(r.get("text") or "", "dim") if state == "starting" else Text("stopping", "yellow")
            elif state == "ready":
                timer, text = f"{r.get('seconds') or 0:.1f}s", Text(r.get("text") or "")
            elif state == "failed":
                timer, text = "", Text(r.get("text") or "failed", "red")
            else:
                timer, text = "", Text(r.get("text") or "", "dim")
            if state != "failed":
                text.truncate(text_width, overflow="ellipsis")
            rows.add_row(icon, Text(LABELS[service]), text, Text(timer, "dim"))
            for extra, extra_style in ((r.get("hint"), ""), (r.get("log") and f"log: {r['log']}", "dim"),
                                       (r.get("note"), "yellow")):
                if extra and state in ("failed", "ready"):
                    line = Text(str(extra), extra_style)
                    if state != "failed":
                        line.truncate(text_width, overflow="ellipsis")
                    rows.add_row(Text(""), Text(""), line, Text(""))

        parts: list[Any] = [head, rule, rows]
        if self.run_line:
            parts.append(Text(f"   {self.run_line}", style="cyan"))
        if self.show_logs:
            parts.append(rule)
            parts.append(self._logs_panel(width))
        parts += [rule, self._keys_line()]
        return Group(*parts)

    def _logs_panel(self, width: int) -> Group:
        tabs = Text(" ")
        for i, service in enumerate(SERVICES):
            name = f" {'vite' if service == 'web' and self.launcher.options.dev else LABELS[service].lower()} "
            tabs.append(name, style="reverse" if i == self.tab else "dim")
            tabs.append(" ")
        tabs.append("  ←/→ switch  esc close", style="dim")
        service = SERVICES[self.tab]
        lines = list(self.logs[service])[-LOG_LINES:]
        body = [tabs]
        for line in lines:
            t = Text(" ")
            t.append(time.strftime("%H:%M:%S", time.localtime(line.at)) + " ", style="dim")
            t.append(f"{line.level or ' '} ", style={"W": "yellow", "E": "red"}.get(line.level, ""))
            t.append(line.text, style=COLOURS[service] if not line.level else "")
            t.truncate(width + 20, overflow="ellipsis")
            body.append(t)
        if not lines:
            body.append(Text(f" nothing yet · full log: {self.launcher._shown(self.launcher.log_path(service))}",
                             style="dim"))
        return Group(*body)

    def _keys_line(self) -> Text:
        failed = any(r["state"] == "failed" for r in self.rows.values())
        keys = []
        if self.launcher.info.urls.get("web"):
            keys.append(("o", "open UI"))
        keys += [("l", "hide logs" if self.show_logs else "logs"),
                 ("r", "retry" if failed else "restart"), ("q", "quit" if failed else "stop")]
        text = Text(" ")
        for key, label in keys:
            text.append(key, style="bold")
            text.append(f" {label}   ", style="dim")
        return text

    # ------------------------------------------------------------------ run --

    def run(self) -> int:
        self.keys.start()
        threading.Thread(target=self._start, daemon=True).start()
        threading.Thread(target=self._poll_runs, daemon=True).start()
        try:
            with Live(self.render(), console=self.console, refresh_per_second=10, transient=True) as live:
                try:
                    while not self._quit.is_set() and not self.launcher.ended.is_set():
                        self._keys()
                        for line in self.filter.flush():
                            self.logs[line.service].append(line)
                        live.update(self.render())
                        time.sleep(0.1)
                except KeyboardInterrupt:
                    self._quit.set()
                self._update_header()
                stopper = threading.Thread(target=self.launcher.stop, daemon=True)
                stopper.start()
                while stopper.is_alive():
                    live.update(self.render())
                    stopper.join(0.1)
        finally:
            self.keys.stop()
            self._done.set()
        self.console.print(" " + self.summary())
        return 0

    def _start(self) -> None:
        with self._busy:
            ok = self.launcher.start()
        if ok or any(r["state"] == "ready" for r in self.rows.values()):
            threading.Thread(target=self.launcher.supervise, daemon=True).start()

    def _keys(self) -> None:
        while not self.keys.queue.empty():
            key = self.keys.queue.get_nowait()
            if key in ("q",):
                self._quit.set()
            elif key == "l":
                self.show_logs = not self.show_logs
            elif key == "esc":
                self.show_logs = False
            elif key in ("left", "right") and self.show_logs:
                self.tab = (self.tab + (1 if key == "right" else -1)) % len(SERVICES)
            elif key == "o" and (url := self.launcher.info.urls.get("web")):
                webbrowser.open(url)
            elif key == "r" and not self._busy.locked():
                threading.Thread(target=self._restart, daemon=True).start()

    def _restart(self) -> None:
        failed = tuple(s for s, r in self.rows.items() if r["state"] == "failed")
        first = not any(self.launcher.info.processes.values())
        self.ready_in = None
        self.launcher.started_at = time.time()
        with self._busy:
            if failed:
                # A failure during start may have left the web row waiting on the backend.
                services = failed + (("web",) if "backend" in failed and not self.launcher.options.dev else ())
                self.launcher.restart(services)
            else:
                self.launcher.restart()
        if first:
            threading.Thread(target=self.launcher.supervise, daemon=True).start()


__all__ = ["StartScreen"]
