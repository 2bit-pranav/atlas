"""Starting, watching and stopping Atlas's processes. Prints nothing.

The launcher emits `Event`s; a view (`views.py`, `screen.py`) shows them.
Three services, started at once and health-checked concurrently, because
neither the backend nor the web UI needs the model to be loaded:

* `llama`: llama-server with the chosen model (the slow one, ~12 s).
* `backend`: the FastAPI app. In normal mode it also serves the built UI.
* `web`: in normal mode, the build in `client/dist` (built once if missing);
  with `--dev`, the Vite dev server with hot reload.

While running, a supervisor thread reports a process that exits, and serves
restart requests from the web UI (Settings > Restart now), which arrive as a
`restart.request` file next to `launched.json`. Every line every process
prints is kept, unfiltered, in `.data/logs/<service>.log` (five starts back).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Callable

import httpx

from agent.cli import launched as rec
from agent.cli.launch import build_backend_args, build_llamacpp_args, build_vite_args, npm
from agent.cli.processes import ProcessGroup, SpawnFailed
from agent.cli.log_filters import parse
from agent.core import llama, paths
from agent.core.settings import Settings, SettingsError, load_settings

SERVICES = ("llama", "backend", "web")
LOG_KEEP = 5
BACKEND_TIMEOUT = 60.0
VITE_TIMEOUT = 60.0


@dataclass
class Event:
    kind: str                      # starting | log_line | ready | failed | exited | stopping | stopped | run
    service: str
    text: str = ""                 # what the row says (starting, ready, run line)
    level: str = ""                # log_line: "", "W", "E"
    raw: str = ""                  # log_line: the line as printed
    seconds: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    hint: str = ""                 # failed: what to do
    lines: list[str] = field(default_factory=list)   # failed: last lines of output
    log: str = ""                  # failed: the log file
    code: int | None = None        # exited


@dataclass
class Options:
    dev: bool = False
    no_llama: bool = False
    no_backend: bool = False
    no_client: bool = False
    health_timeout: float = 180.0


class Launcher:
    def __init__(self, root: Path, settings_path: Path, launched_path: Path, options: Options,
                 emit: Callable[[Event], None]) -> None:
        self.root = root
        self.settings_path = settings_path
        self.launched_path = launched_path
        self.options = options
        self.emit = emit
        self.settings: Settings = load_settings(settings_path)
        self.group = ProcessGroup()
        self.info = rec.LaunchedInfo.new("dev" if options.dev else "normal")
        self.state: dict[str, str] = {}
        self.started_at = time.time()
        self._logs: dict[str, IO[str]] = {}
        self._stopping = threading.Event()
        #: Set when `atlas stop`, run elsewhere, ended this launch.
        self.ended = threading.Event()
        self._restarting = threading.Lock()
        #: One per launch, kept across restarts: llama-server and the backend share it.
        self.llama_key = secrets.token_urlsafe(24)
        self.request_file = launched_path.with_name("restart.request")
        self.status_file = launched_path.with_name("restart.json")

    # ------------------------------------------------------------ helpers --

    @property
    def log_dir(self) -> Path:
        return paths.data_dir(self.settings) / "logs"

    def log_path(self, service: str) -> Path:
        return self.log_dir / f"{service}.log"

    def _open_log(self, service: str, rotate: bool) -> IO[str]:
        """The service's log file; at a fresh start the previous ones move down one."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_path(service)
        if rotate and path.exists():
            try:
                for n in range(LOG_KEEP - 1, 0, -1):
                    older = self.log_dir / f"{service}.{n}.log"
                    if older.exists():
                        os.replace(older, self.log_dir / f"{service}.{n + 1}.log")
                os.replace(path, self.log_dir / f"{service}.1.log")
            except OSError:
                pass  # held open by another process (Windows): keep appending to it
        if service in self._logs:
            self._logs[service].close()
        self._logs[service] = path.open("a", encoding="utf-8", errors="replace")
        return self._logs[service]

    def _on_line(self, service: str, raw: str) -> None:
        level, text = parse(service, raw)
        self.emit(Event("log_line", service, text=text, level=level, raw=raw))

    def _set(self, service: str, state: str) -> None:
        self.state[service] = state

    def _fail(self, service: str, reason: str, hint: str = "", lines: list[str] | None = None) -> bool:
        self._set(service, "failed")
        self.emit(Event("failed", service, text=reason, hint=hint, lines=lines or [],
                        log=self._shown(self.log_path(service))))
        return False

    def _shown(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def _port_free(self, service: str, port: int, key: str) -> bool:
        owner = rec.port_owner(port)
        if owner is None:
            return True
        pid, name = owner
        return self._fail(service, f"port {port} is in use by PID {pid} ({name})",
                          f"Another Atlas may be running: try `atlas stop`, or change ports.{key}.")

    def _wait(self, service: str, proc: subprocess.Popen[bytes], url: str, timeout: float) -> bool:
        """Until `url` answers 2xx, the process exits, or `timeout` passes."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stopping.is_set():
            if proc.poll() is not None:
                return False
            if rec.http_ok(url):
                return True
            time.sleep(0.25)
        return False

    def _last(self, service: str, n: int = 12) -> list[str]:
        entry = self.group.get(service)
        return entry[1].last(n) if entry else []

    # ------------------------------------------------------------ services --

    def _start_llama(self, rotate: bool) -> bool:
        s = self.settings
        started = time.monotonic()
        self._set("llama", "starting")
        self.emit(Event("starting", "llama", text=f"{s.model.name} · loading"))
        binary = s.llamacpp.binary
        if not (shutil.which(binary) or Path(binary).is_file()):
            return self._fail("llama", f"`{binary}` is not on PATH", "Set llamacpp.binary in settings.json.")
        try:
            args = build_llamacpp_args(s, api_key=self.llama_key)
        except llama.ModelError as exc:
            return self._fail("llama", str(exc), "Pick a model in Settings > Model, or set model.name.")
        if not self._port_free("llama", s.ports.llama, "llama"):
            return False
        try:
            proc, _ = self.group.spawn("llama", args, cwd=self.root, log=self._open_log("llama", rotate),
                                       on_line=self._on_line)
        except SpawnFailed as exc:
            return self._fail("llama", str(exc), "Set llamacpp.binary in settings.json.")
        url = f"http://127.0.0.1:{s.ports.llama}"
        if not self._wait("llama", proc, f"{url}/health", self.options.health_timeout):
            lines = self._last("llama")
            self.group.stop("llama")
            if self._stopping.is_set():
                return False
            if proc.poll() is not None:
                return self._fail("llama", f"llama-server stopped while loading (exit {proc.returncode})",
                                  "The model may not fit: lower Context size or GPU layers.", lines)
            return self._fail("llama", f"llama-server did not become ready in {self.options.health_timeout:.0f} s",
                              "Last lines below.", lines)
        self.info.processes["llama"] = rec.process_entry(proc.pid)
        chosen = llama.current(s)
        self.info.model = {"name": chosen.name, "gguf": rec.fingerprint(chosen.gguf),
                           "mmproj": rec.fingerprint(chosen.mmproj)}
        self._set("llama", "ready")
        self.emit(Event("ready", "llama", seconds=time.monotonic() - started, details=self._model_details(url)))
        return True

    def _model_details(self, url: str) -> dict[str, Any]:
        s = self.settings
        details: dict[str, Any] = {"name": s.model.name, "gpu": str(s.model.gpu_layers) != "0"}
        try:
            props = httpx.get(f"{url}/props", timeout=2,
                              headers={"Authorization": f"Bearer {self.llama_key}"}).json()
            details["ctx"] = (props.get("default_generation_settings") or {}).get("n_ctx") or s.model.context_size
            details["vision"] = bool((props.get("modalities") or {}).get("vision"))
        except (httpx.HTTPError, ValueError):
            details["ctx"] = s.model.context_size
        return details

    def _start_backend(self, rotate: bool) -> bool:
        s = self.settings
        started = time.monotonic()
        self._set("backend", "starting")
        self.emit(Event("starting", "backend", text=f"127.0.0.1:{s.ports.backend}"))
        if not self._port_free("backend", s.ports.backend, "backend"):
            return False
        env = dict(os.environ, ATLAS_SETTINGS=str(self.settings_path.resolve()), ATLAS_ROOT=str(self.root),
                   PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                   ATLAS_RESTART_REQUEST=str(self.request_file), ATLAS_RESTART_STATUS=str(self.status_file),
                   ATLAS_LAUNCHED=str(self.launched_path.resolve()),
                   **{llama.KEY_ENV: self.llama_key})
        if self.options.dev:
            # Pages on the backend's port go to Vite, never to an old build.
            env["ATLAS_DEV_UI"] = f"http://127.0.0.1:{s.ports.client}"
        try:
            proc, _ = self.group.spawn("backend", build_backend_args(s), cwd=self.root, env=env,
                                       log=self._open_log("backend", rotate), on_line=self._on_line)
        except SpawnFailed as exc:
            return self._fail("backend", str(exc))
        url = f"http://127.0.0.1:{s.ports.backend}"
        if not self._wait("backend", proc, f"{url}/api/health", BACKEND_TIMEOUT):
            lines = self._last("backend", 20)
            self.group.stop("backend")
            if self._stopping.is_set():
                return False
            return self._fail("backend", "the backend stopped while starting" if proc.poll() is not None
                              else f"the backend did not answer in {BACKEND_TIMEOUT:.0f} s",
                              "Last lines of its output below.", lines)
        self.info.processes["backend"] = rec.process_entry(proc.pid)
        self.info.urls["backend"] = url
        self._set("backend", "ready")
        self.emit(Event("ready", "backend", seconds=time.monotonic() - started, details={"url": url}))
        return True

    def _start_web(self, rotate: bool, backend_ready: threading.Event) -> bool:
        started = time.monotonic()
        self._set("web", "starting")
        if self.options.dev:
            return self._start_vite(rotate, started)
        dist = self.root / "client" / "dist" / "index.html"
        if not dist.is_file():
            self.emit(Event("starting", "web", text="building the web UI (once)"))
            if not self._build_client(rotate):
                return False
        self.emit(Event("starting", "web", text="served by backend"))
        backend_ready.wait()
        if self.state.get("backend") != "ready":
            self._set("web", "idle")
            self.emit(Event("stopped", "web", text="not started"))
            return False
        url = self.info.urls["backend"]
        self.info.urls["web"] = url
        self._set("web", "ready")
        self.emit(Event("ready", "web", seconds=time.monotonic() - started,
                        details={"url": url, "stale": self._client_stale(dist)}))
        return True

    def _build_client(self, rotate: bool) -> bool:
        exe = npm()
        if not exe:
            return self._fail("web", "the web UI is not built and Node.js is not installed",
                              "Install Node.js once to build it, or use a release that includes client/dist.")
        log = self._open_log("web", rotate)
        client = self.root / "client"
        steps = [] if (client / "node_modules").is_dir() else [[exe, "install"]]
        for args in [*steps, [exe, "run", "build"]]:
            proc = subprocess.run(args, cwd=client, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
            log.write(proc.stdout + proc.stderr)
            log.flush()
            if proc.returncode != 0:
                return self._fail("web", f"`npm {' '.join(args[1:])}` failed",
                                  "Last lines below.", (proc.stdout + proc.stderr).strip().splitlines()[-12:])
        return True

    def _client_stale(self, dist: Path) -> bool:
        """The UI sources changed after the build: the served UI is older than the code."""
        built = dist.stat().st_mtime
        client = self.root / "client"
        sources = [*(client / "src").rglob("*"), client / "index.html", client / "package.json"]
        return any(p.is_file() and p.stat().st_mtime > built for p in sources)

    def _start_vite(self, rotate: bool, started: float) -> bool:
        s = self.settings
        url = f"http://127.0.0.1:{s.ports.client}"
        self.emit(Event("starting", "web", text="vite"))
        if not self._port_free("web", s.ports.client, "client"):
            return False
        try:
            args = build_vite_args(s)
            proc, _ = self.group.spawn("web", args, cwd=self.root / "client",
                                       env=dict(os.environ, VITE_ATLAS_BACKEND_PORT=str(s.ports.backend)),
                                       log=self._open_log("web", rotate), on_line=self._on_line)
        except (SpawnFailed, FileNotFoundError) as exc:
            return self._fail("web", str(exc), "Install Node.js, or start without --dev.")
        if not self._wait("web", proc, url, VITE_TIMEOUT):
            lines = self._last("web")
            self.group.stop("web")
            return False if self._stopping.is_set() else self._fail("web", "Vite did not start", "Last lines below.", lines)
        self.info.processes["web"] = rec.process_entry(proc.pid)
        self.info.urls["web"] = url
        self._set("web", "ready")
        self.emit(Event("ready", "web", seconds=time.monotonic() - started, details={"url": url}))
        return True

    # ------------------------------------------------------------- control --

    def start(self, services: tuple[str, ...] | None = None, rotate: bool = True) -> bool:
        """Start the services in parallel; True when every one is ready."""
        wanted = services or tuple(s for s in SERVICES if not self._skipped(s))
        for service in SERVICES:
            if self._skipped(service):
                self._set(service, "skipped")
                self.emit(Event("stopped", service, text=f"not started (--no-{'client' if service == 'web' else service})"))
        backend_ready = threading.Event()
        if "backend" not in wanted:
            backend_ready.set()

        def backend() -> None:
            try:
                self._start_backend(rotate)
            finally:
                backend_ready.set()

        jobs = {"llama": lambda: self._start_llama(rotate), "backend": backend,
                "web": lambda: self._start_web(rotate, backend_ready)}

        def guarded(service: str) -> None:
            try:
                jobs[service]()
            except Exception as exc:  # noqa: BLE001 - a bug here must still end as a failed row
                self._fail(service, f"unexpected error: {type(exc).__name__}: {exc}",
                           "Please report it with the log file.")

        threads = [threading.Thread(target=guarded, args=(s,), daemon=True) for s in wanted]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self._record()
        ok = all(self.state.get(s) == "ready" for s in wanted)
        self._write_status("ready" if ok else "failed", error=None if ok else self._first_failure())
        return ok

    def _skipped(self, service: str) -> bool:
        o = self.options
        return {"llama": o.no_llama, "backend": o.no_backend, "web": o.no_client or (o.no_backend and not o.dev)}[service]

    def _first_failure(self) -> str | None:
        return next((s for s, st in self.state.items() if st == "failed"), None)

    def _record(self) -> None:
        running = self.group.running()
        self.info.processes = {s: e for s, e in self.info.processes.items() if s in running}
        rec.write_launched(self.launched_path, self.info, self.settings.model_dump(mode="json"))

    def _write_status(self, state: str, **fields: Any) -> None:
        self.status_file.write_text(json.dumps({"state": state, "at": int(time.time() * 1000),
                                                "model": self.settings.model.name, **fields}), encoding="utf-8")

    def restart(self, services: tuple[str, ...] | None = None) -> bool:
        """Restart the model and the backend (or `services`) with the settings on disk.

        The web UI keeps running: in normal mode it is the backend's, and Vite
        reconnects by itself. From the web UI, a model change applies this way.
        """
        if not self._restarting.acquire(blocking=False):
            return False
        try:
            self._write_status("restarting")
            try:
                self.settings = load_settings(self.settings_path)
            except SettingsError as exc:
                self._write_status("failed", error=str(exc))
                return False
            wanted = services or tuple(s for s in ("llama", "backend") if not self._skipped(s))
            for service in wanted:
                self.emit(Event("stopping", service))
                self.group.stop(service)
                self._set(service, "stopped")
            ok = self.start(wanted, rotate=False)
            if "backend" in wanted and self.state.get("web") == "ready" and not self.options.dev:
                self.emit(Event("ready", "web", seconds=0.0, details={"url": self.info.urls.get("web", "")}))
            return ok
        finally:
            self._restarting.release()

    def supervise(self, poll: float = 0.5) -> None:
        """Report processes that exit; serve restart requests. Returns when stopping."""
        while not self._stopping.wait(poll):
            if not self.launched_path.exists():
                self.ended.set()  # `atlas stop` deletes it: the view exits
                return
            if self.request_file.exists():
                self.request_file.unlink(missing_ok=True)
                threading.Thread(target=self.restart, daemon=True).start()
                continue
            if self._restarting.locked():
                continue
            running = self.group.running()
            gone = [s for s in SERVICES
                    if self.state.get(s) == "ready" and s in self.info.processes and s not in running]
            if gone and (self._stopping.wait(0.3) or not self.launched_path.exists()):
                self.ended.set()  # stopped on purpose (`atlas stop`), not a crash
                return
            for service in gone:
                entry = self.group.get(service)
                code = entry[0].returncode if entry else None
                self.emit(Event("exited", service, code=code))
                self._fail(service, f"{'llama-server' if service == 'llama' else service} exited (code {code})",
                           "Press r to restart it.", self._last(service))

    def active_run(self) -> dict[str, Any] | None:
        url = self.info.urls.get("backend")
        if not url or self.state.get("backend") != "ready":
            return None
        try:
            return httpx.get(f"{url}/api/health", timeout=1.5).json().get("active_run")
        except (httpx.HTTPError, ValueError):
            return None

    def stop(self) -> None:
        self._stopping.set()
        for service in reversed(SERVICES):
            if self.state.get(service) in ("ready", "starting", "failed"):
                started = time.monotonic()
                self.emit(Event("stopping", service))
                self.group.stop(service)
                self._set(service, "stopped")
                self.emit(Event("stopped", service, seconds=time.monotonic() - started))
        self.group.close()
        # Anything of ours left on the ports this launch used (a grandchild the
        # tree kill missed). The client port is only ours with --dev.
        s = self.settings
        ports = {"backend": s.ports.backend, "llama": s.ports.llama, "web": s.ports.client}
        rec.stop_by_port({k: v for k, v in ports.items() if k in self.group.spawned})
        for path in (self.launched_path, self.request_file, self.status_file):
            path.unlink(missing_ok=True)
        for log in self._logs.values():
            log.close()


__all__ = ["Event", "Launcher", "Options", "SERVICES"]
