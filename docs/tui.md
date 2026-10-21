# CLI and start screen

How `atlas start` and its companions look and behave. Two modes: a compact
Textual screen for everyday use, and a dev mode with more detail that still
does not flood the terminal.

Status: built, 2026-10-21. One change from this design: the start screen is
Rich Live, not Textual. Textual's inline mode does not exist on Windows (it
falls back to full screen), and Rich is already a dependency of the dev view.
The model failure names the missing folder in `llm/` (models are picked by
folder name, not `model.path`).

**Out of scope: chat in the terminal.** The web UI is the place to chat. The
"TUI" here is the start screen and status panel only.

---

## What is wrong today

From a normal `atlas start`:

- **Banners.** Every start and stop is a three-line `=====` block: about 25
  lines of the screen for six events.
- **Everything is streamed.** llama-server's tokenizer warnings, its own
  timestamps beside ours, every polled `GET /api/settings`, every Vite HMR
  update.
- **Long lines wrap**, so one log line takes two or three rows.
- **Two timestamps per line** (`17:20:04 [llama] 0.01.810.550 I srv ...`).
- **No summary.** Whether Atlas is up, and where, has to be read out of the log.
- **Sequential start.** The backend and client wait for the model to load,
  though neither needs it.

---

## Commands

| Command | What it does |
|---|---|
| `atlas start` | The start screen (below). Stays open as a live status panel |
| `atlas start --dev` | Dev mode: Vite with hot reload, filtered logs, pinned status line |
| `atlas start --dev --raw` | Every line from every process, unfiltered, as today minus the banners |
| `atlas start --no-llama` / `--no-backend` / `--no-client` | A subset, as today |
| `atlas stop` | Stops everything, one line per service |
| `atlas status` | What is running, on which ports, since when |
| `atlas logs [llama\|backend\|client] [-f] [-n N]` | The log files the quiet start does not show |
| `atlas settings check` / `show` | Unchanged |

`atlas start` when Atlas is already running prints its status and says so,
instead of failing on a busy port.

---

## Normal mode: the start screen

A Textual app in **inline mode** (`App.run(inline=True)`): drawn below the
prompt, about eight lines tall, never full screen.

### Starting

```
 Atlas                                              starting…
 ─────────────────────────────────────────────────────────────
 ⠼ Model     unsloth_e2b_qat · loading                   6.1s
 ✓ Backend   127.0.0.1:8000                              1.2s
 ✓ Web UI    served by backend
 ─────────────────────────────────────────────────────────────
 l logs   q stop
```

All three start **in parallel**. The model row shows a spinner and elapsed
time; the others usually finish first.

### Ready

```
 Atlas                                        ready in 12.8s
 ─────────────────────────────────────────────────────────────
 ✓ Model     unsloth_e2b_qat · 32k ctx · vision · GPU   12.8s
 ✓ Backend   127.0.0.1:8000                              1.2s
 ✓ Web UI    http://127.0.0.1:8000                       0.0s
 ─────────────────────────────────────────────────────────────
 o open UI   l logs   r restart   q stop
```

The screen stays as a live panel while Atlas runs: a row turns red if its
process exits, and a small line under the rows shows the active run, if any
("running · chat “Results sem 6” · 14 tok/s").

### Failure

```
 Atlas                                                 failed
 ─────────────────────────────────────────────────────────────
 ✗ Model     port 8080 is in use by PID 4312 (llama-server.exe)
             Another Atlas may be running: try `atlas stop`.
             log: .data/logs/llama.log
 · Backend   not started
 · Web UI    not started
 ─────────────────────────────────────────────────────────────
 l logs   r retry   q quit
```

A failure is **one sentence of what happened and one of what to do**, the
log path, and on `l`, the last lines. Known failures and their messages:

| Failure | Message |
|---|---|
| Port busy (`WinError 10013` on Windows, which reads like a permissions error) | Port N is in use by PID p (name). Try `atlas stop`, or change `ports.*` |
| `model.path` / `model.mmproj_path` missing | The model file was not found at <path>. Check `model.path` in settings.json |
| llama.cpp binary not found | `llama` is not on PATH. Set `llamacpp.binary` |
| Health check timed out | llama-server did not become ready in 180 s. Last lines below |
| Backend exits during start | The backend stopped while starting. Last lines of its traceback below |
| `settings.json` invalid | The `atlas settings check` output, as today |
| Web UI build missing | Builds it once (see below), with its own spinner row |

### Logs

`l` expands an inline panel (about 15 lines) under the rows, with a tab per
service. `Esc` collapses it. Lines are filtered as in dev mode (below). The
panel never takes the whole terminal.

### Keys

| Key | Action |
|---|---|
| `o` | Open the web UI in the browser |
| `l` | Show or hide logs |
| `r` | Restart (all, or the failed service) |
| `q`, `Ctrl+C` | Stop everything and exit |

Bind `Ctrl+C` explicitly: it is what people press, and recent Textual versions
do not quit on it by default. Stopping redraws the rows as `stopping`, then
the app exits leaving one line in the scrollback:

```
 Atlas stopped cleanly · up 46m · 3 runs
```

### When Textual is not used

Textual needs a terminal. When stdout is not a TTY (piped, redirected, a CI
log), `atlas start` falls back to the plain view: one line per event, no
spinners, no colours.

---

## Dev mode

`atlas start --dev`. Built for working on Atlas: more detail than the start
screen, but still filtered.

**Not Textual.** Dev mode prints to the terminal's normal scrollback, so
tracebacks can be scrolled, searched and copied. It uses Rich (already a
dependency, and the library Textual is built on) for a **status line pinned
at the bottom**, with filtered logs scrolling above it:

```
 17:20:14 llama     W  audio input is experimental
 17:20:15 llama        model loaded · 32k ctx · 1 slot
 18:04:22 backend      GET /api/settings, /api/chats  200  ×4
 18:05:10 backend      run 3f2a · chat “Results sem 6” · 2 model calls · 14.2s
 18:06:32 vite         hmr · 12 files
 18:06:32 vite      W  Fast Refresh off: Composer.tsx exports "formatBytes"
 ─────────────────────────────────────────────────────────────────────────
 Atlas dev  llama ✓ 12.8s  backend ✓ 1.1s  vite ✓ 0.6s   http://127.0.0.1:5173
```

### Line format

- **One timestamp**, ours. Each process's own prefix is stripped: llama's
  `0.01.810.550 I srv  func:`, Vite's `6:06:32 pm [vite] (client)`, uvicorn's
  `INFO:`.
- **A fixed service column** (`llama`, `backend`, `vite`), one colour each.
- **A level column**: blank for info, `W` yellow, `E` red.
- **Truncated to the terminal width**, never wrapped. The full line is in the
  log file.

### Filters

Each service has a small list of rules: **drop**, **collapse** or **rewrite**.
They live in one module, with the patterns taken from real output.

| Service | Rule | Example |
|---|---|---|
| llama | drop | `control-looking token ...`, `removing it from EOG list`, `common_params_print_info`, `The UI is disabled`, the default-port notice |
| llama | rewrite | the load sequence becomes `model loaded · 32k ctx · 1 slot` |
| llama | keep | every `E` line; `W` lines not on the drop list |
| backend | collapse | repeated access-log lines within a few seconds: `GET /api/settings, /api/chats 200 ×4` |
| backend | keep | non-2xx responses, every `atlas.*` / `agent.*` log line, tracebacks in full |
| backend | rewrite | a finished run becomes one line: id, chat, model calls, duration |
| vite | collapse | a burst of `hmr update` lines becomes `hmr · N files` |
| vite | keep | `hmr invalidate` and every warning or error, shortened |

**Errors and tracebacks are never filtered or truncated.** A traceback prints
in full and wraps, because cutting it is worse than flooding.

`--raw` turns every filter off, for the rare case where a dropped line
matters.

### Debugging the backend

A breakpoint in the backend runs in a subprocess whose input is not the
terminal, so `pdb` there will not work under `atlas start` in any mode. The
way to debug it: `atlas start --dev --no-backend`, and run the backend from the
IDE or a second terminal with `python -m server.main`.

---

## Log files

Every line from every process goes to `.data/logs/<service>.log` in **every**
mode, unfiltered. Each start rotates the previous file (`llama.log` ->
`llama.1.log`), keeping the last five. `atlas logs` reads these.

---

## Code changes

### One launcher, three views

Today `ProcessGroup` gives each process a `LogRelay` that writes to a text
stream, with a banner around it, so supervising and printing are tangled.
Split them:

- **`Launcher`** (`agent/cli/launcher.py`): starts, health-checks, supervises
  and stops processes. It prints nothing; it emits events:

  | Event | Fields |
  |---|---|
  | `starting` | service |
  | `log_line` | service, level, text, raw |
  | `ready` | service, seconds, details (url, ctx, slots) |
  | `failed` | service, reason, hint, last lines, log path |
  | `exited` | service, code |
  | `stopping` / `stopped` | service, seconds |

- **Views**, each a consumer of those events:
  - `StartScreen` (Textual): normal mode on a TTY.
  - `DevView` (Rich, pinned status line, filtered): `--dev`.
  - `PlainView` (one line per event or log line): `--raw`, and any non-TTY.
- **`LogRelay`** writes every line to the service's log file and hands it to
  the launcher as a `log_line` event. The banner and `BANNER_WIDTH` go.
- **`log_filters.py`**: the per-service rules above. Shared by `DevView` and
  the start screen's log panel.
- **`cmd_start`** is split: settings, port checks, stale-process cleanup,
  spawning, `launched.json` and supervision move into the launcher;
  `main.py` keeps argument parsing and picks the view. The signal handlers
  move into the views (Textual installs its own).

### Parallel start

The backend and client do not need the model to be loaded. Start all three
at once and wait on each health check concurrently, so the model load (about
12 s) overlaps the rest.

### Serve the built web UI from the backend

Normal mode no longer runs Vite or needs Node:

- The backend serves `client/dist` with FastAPI's `StaticFiles`, on the API's
  own port and origin.
- If `client/dist` is missing, `atlas start` builds it once (`npm run build`)
  with its own spinner row. If the sources are newer than the build, it says
  so on the Web UI row and suggests `--dev` or rebuilding.
- `--dev` runs Vite with hot reload, as today.

This removes a process and a port from normal use, and puts the UI on the
same origin as the API, which simplifies the extension's CORS lockdown (see
`extension.md`).

### Model hash

`launched.py` hashes the GGUF files. The fingerprint (size and modified time)
looks like it skips the hash when nothing changed. Confirm it on the real
machine: hashing a multi-GB model on every start would cost seconds.

### Dependencies

`textual` added to `requirements.in`. `rich` is already there.

---

## Noticed in the current output

Not part of this change, but found while reading the logs:

- **llama-server accepts requests from any website.** It warns that no API
  key is set and CORS allows all origins. A page in the browser could call
  `127.0.0.1:8080` directly. Start it with `--api-key` set to a key generated
  per launch, and have the backend send it. Same reasoning as the extension's
  pairing token.
- **llama.cpp's default port is changing** to 9931 in a future release.
  Atlas should always pass `--port` from settings; check it does.
- **Fast Refresh is off for two components.** `Composer.tsx` exports
  `formatBytes` and `MentionMenu.tsx` exports `filterMentions` beside their
  components, so Vite reloads them fully. Move both helpers into `lib/`,
  which also suits sharing code with the extension.
- **Polling pairs.** `GET /api/settings` and `GET /api/chats` arrive twice in
  the same second. Likely React StrictMode running effects twice in
  development; harmless, and collapsed by the dev filters.

---

## Done when

- `atlas start` shows the start screen and nothing else; it is never taller
  than about eight lines unless logs are opened.
- Model, backend and web UI start in parallel.
- Every failure in the table explains itself in one line, with the log path.
- `atlas start --dev` shows filtered, single-line logs with one pinned status
  line, and never wraps anything except a traceback.
- `--raw` shows everything; `atlas logs` shows the files.
- Normal mode runs without Node.
- Piped output falls back to plain lines.
