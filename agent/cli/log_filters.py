"""What the dev view and the start screen's log panel show of each process.

Two steps. `parse` turns a raw line into (level, text): the process's own
timestamp and prefix are stripped (llama's `0.01.810.550 I srv  func:`,
uvicorn's `INFO:`, Vite's `6:06:32 pm [vite] (client)`), and the level is
"" (info), "W" or "E". `LogFilter` then applies each service's rules:

* llama: keep errors and the warnings that matter; drop the known noise
  (tokenizer notices, the UI and API-key banners); the load sequence becomes
  one line, `model loaded · 32k ctx · 1 slot`.
* backend: successful requests within a few seconds collapse into one line
  per method (`GET /api/settings, /api/chats  200  ×4`); other statuses,
  Atlas's own log lines and tracebacks are kept.
* vite: a burst of hot updates collapses into `hmr · N files`; warnings and
  errors are kept.

Errors and tracebacks are never dropped or shortened. The log files always
hold everything, unfiltered.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

#: How long a collapsed group waits for more lines before it is shown.
COLLAPSE_SECONDS = 3.0
#: Polled by the start screen and the web UI every few seconds: never shown when they succeed.
QUIET_PATHS = {"/api/health", "/api/restart"}


@dataclass
class Line:
    service: str
    level: str
    text: str
    at: float = field(default_factory=time.time)
    #: Part of a traceback: printed whole, never truncated.
    traceback: bool = False


# ------------------------------------------------------------------- parsing --

_LLAMA = re.compile(r"^\d+\.\d+\.\d+\.\d+\s+([IWEDT])\s+(.*)$")
#: llama's module column (`srv  `, `cmn  `) and function column (`load_model: `).
_LLAMA_PREFIX = re.compile(r"^(?:[a-z]{2,4}\s{2,})?\s*\w{1,16}:\s+")
_UVICORN = re.compile(r"^(INFO|WARNING|ERROR|CRITICAL|DEBUG):\s+(.*)$")
_PYLOG = re.compile(r"^(INFO|WARNING|ERROR|CRITICAL|DEBUG) ([\w.]+): (.*)$")
_VITE = re.compile(r"^\d{1,2}:\d{2}:\d{2}\s*(?:[ap]m)?\s*\[vite\]\s*(?:\(\w+\)\s*)?", re.I)
_LEVEL = {"INFO": "", "DEBUG": "", "WARNING": "W", "ERROR": "E", "CRITICAL": "E", "I": "", "D": "",
          "T": "", "W": "W", "E": "E"}


def parse(service: str, raw: str) -> tuple[str, str]:
    """(level, text) of one raw line, without the process's own prefix."""
    if service == "llama":
        m = _LLAMA.match(raw)
        if m:
            return _LEVEL[m.group(1)], _LLAMA_PREFIX.sub("", m.group(2), count=1).strip()
        return "", raw.strip()
    if service == "backend":
        if m := _PYLOG.match(raw):
            return _LEVEL[m.group(1)], f"{m.group(2)}: {m.group(3)}"
        if m := _UVICORN.match(raw):
            return _LEVEL[m.group(1)], m.group(2).strip()
        return "", raw.rstrip()
    if service in ("web", "vite"):
        text = _VITE.sub("", raw).strip()
        low = text.lower()
        level = "E" if ("error" in low or "✘" in text) else "W" if ("warn" in low or "could not fast refresh" in low) else ""
        return level, text
    return "", raw.strip()


# ------------------------------------------------------------------- filters --

_LLAMA_DROP = re.compile("|".join([
    r"control-looking token", r"removing it from EOG list", r"is a normal token here",
    r"common_params_print_info", r"The UI is disabled", r"--ui/--no-ui",
    r"no API key is set", r"default port", r"^https?://\S+$",
]), re.I)
_LLAMA_CTX = re.compile(r"n_slots = (\d+), n_ctx_slot = (\d+)")
_ACCESS = re.compile(r'^[\d.:]+ - "(\w+) (\S+) HTTP/[\d.]+" (\d{3})')
_BACKEND_DROP = re.compile(
    r"^(Started server process|Waiting for application startup|Application startup complete|"
    r"Uvicorn running on|Shutting down|Waiting for application shutdown|Application shutdown complete|"
    r"Finished server process)")
_VITE_DROP = re.compile(r"^(VITE v|➜|press h|>|$)")
_HMR = re.compile(r"^hmr update (.*)$")
_TB_START = re.compile(r"^Traceback \(most recent call last\)")
_TB_END = re.compile(r"^[\w.]+(Error|Exception|Exit|Interrupt)\b")


class LogFilter:
    """Stateful filter over all services' lines; `raw=True` lets everything through."""

    def __init__(self, raw: bool = False) -> None:
        self.raw = raw
        self._ctx: dict[str, int] = {}
        self._access: dict[tuple[str, str], list] = {}   # (method, status) -> [paths, count, first]
        self._hmr: list = []                            # [files, first, service]
        self._in_tb = False

    def feed(self, service: str, level: str, text: str) -> list[Line]:
        if self.raw:
            return [Line(service, level, text)]
        if service in ("web", "vite"):
            return self._vite(service, level, text)
        handler = {"llama": self._llama, "backend": self._backend}.get(service)
        return handler(level, text) if handler else [Line(service, level, text)]

    def flush(self, force: bool = False) -> list[Line]:
        """Collapsed groups whose window has passed (all of them when `force`)."""
        now = time.time()
        out = []
        for key, (paths, count, first) in list(self._access.items()):
            if force or now - first >= COLLAPSE_SECONDS:
                method, status = key
                more = f"  ×{count}" if count > 1 else ""
                out.append(Line("backend", "", f"{method} {', '.join(paths)}  {status}{more}", first))
                del self._access[key]
        if self._hmr and (force or now - self._hmr[1] >= COLLAPSE_SECONDS / 2):
            files = self._hmr[0]
            out.append(Line(self._hmr[2], "", f"hmr · {len(files)} file{'s' * (len(files) != 1)}", self._hmr[1]))
            self._hmr = []
        return out

    def _llama(self, level: str, text: str) -> list[Line]:
        if level == "E":
            return [Line("llama", "E", text)]
        if m := _LLAMA_CTX.search(text):
            self._ctx = {"slots": int(m.group(1)), "ctx": int(m.group(2))}
            return []
        if text == "model loaded":
            ctx = self._ctx.get("ctx")
            slots = self._ctx.get("slots")
            parts = ["model loaded"]
            if ctx:
                parts.append(f"{ctx // 1024}k ctx" if ctx >= 1024 else f"{ctx} ctx")
            if slots:
                parts.append(f"{slots} slot{'s' * (slots != 1)}")
            return [Line("llama", "", " · ".join(parts))]
        if level == "W" and not _LLAMA_DROP.search(text):
            return [Line("llama", "W", text)]
        return []

    def _backend(self, level: str, text: str) -> list[Line]:
        if _TB_START.match(text):
            self._in_tb = True
        if self._in_tb:
            if _TB_END.match(text):
                self._in_tb = False
            return [Line("backend", "E", text, traceback=True)]
        if m := _ACCESS.match(text):
            method, path, status = m.groups()
            if status.startswith("2") and path.split("?")[0] in QUIET_PATHS:
                return []
            if not status.startswith("2"):
                return [Line("backend", "W" if status.startswith("4") else "E", f"{method} {path}  {status}")]
            entry = self._access.setdefault((method, status), [[], 0, time.time()])
            if path.split("?")[0] not in entry[0]:
                entry[0].append(path.split("?")[0])
            entry[1] += 1
            return []
        if _BACKEND_DROP.match(text):
            return []
        # Atlas's own lines arrive as `agent.core.x: message`; the logger name is noise here.
        return [Line("backend", level, re.sub(r"^(?:agent|server)[\w.]*: ", "", text))]

    def _vite(self, service: str, level: str, text: str) -> list[Line]:
        if level:
            return [Line(service, level, text)]
        if m := _HMR.match(text):
            files = self._hmr[0] if self._hmr else []
            files.extend(f for f in m.group(1).split(", ") if f not in files)
            self._hmr = [files, self._hmr[1] if self._hmr else time.time(), service]
            return []
        if text.startswith("hmr invalidate"):
            return [Line(service, "W", text)]
        if _VITE_DROP.match(text):
            return []
        return [Line(service, "", text)]


__all__ = ["COLLAPSE_SECONDS", "Line", "LogFilter", "parse"]
