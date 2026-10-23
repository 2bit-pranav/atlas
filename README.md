# Atlas

A local agent: a small model on your own machine, with tools, skills and MCP
servers, and nothing sent to a cloud unless you add a remote MCP server or
switch on `web_fetch`.

- **Model:** llama.cpp's `llama-server`, configured for Gemma (2B effective,
  32k context, vision via mmproj).
- **Agent:** the [Strands](https://strandsagents.com) harness. Strands owns the
  agent loop, the tools, skills, MCP connections and the model's history;
  Atlas configures it and adds what Strands does not have: a chat tree with
  versions, runs that outlive the browser, an HTTP API and a web UI.
- **UI:** React, modelled on llama.cpp's own web UI.

## Running it

```
pip install -e .                 # once, into .venv; provides the `atlas` command
cp settings.example.json settings.json   # then set model.name (see below)
atlas start                      # the model, the backend and the web UI, at http://127.0.0.1:8000
atlas stop                       # stops everything, one line per service
atlas status                     # what is running, on which ports, since when
atlas logs [llama|backend|web]   # the full logs (-f to follow, -n N lines)
```

`atlas start` shows a small live panel (o opens the UI, l shows logs, r
restarts, q stops). The backend serves the built UI, so normal use needs no
Node; the first start builds it if `client/dist` is missing. `atlas start
--dev` runs Vite with hot reload instead (UI at :5173) and prints filtered
logs under a pinned status line; `--raw` prints every line unfiltered. Logs
are kept in `.data/logs/`, five starts back.

Models live in `llm/`, one subfolder each with its `.gguf` (and an `mmproj`
file for image input): `llm/gemma/`. Pick one under Settings > Model and
press "Restart now" at the top of Settings; llama-server and the backend
restart with it.

`atlas start --no-llama`, `--no-backend` and `--no-client` start a subset.
`atlas settings check` validates `settings.json`; `atlas settings show
--restart-required` lists saved settings the running servers do not have yet.

Open http://127.0.0.1:8000 (5173 with `--dev`). Ports come from `settings.json` and nowhere else.

Do not start the backend with `uvicorn --reload`: on Windows its worker runs
an event loop that cannot start subprocesses, so every shell call and every
skill fails with an empty error. `atlas start` never uses it.

## Where things are

| Path | What | Read |
|---|---|---|
| `agent/` | The agent library: settings, the agent factory, the model adapter, the chat tree, skills, MCP, the CLI | [agent/AGENTS.md](agent/AGENTS.md) |
| `server/` | FastAPI: runs, the event stream, the HTTP API | [server/AGENTS.md](server/AGENTS.md) |
| `client/` | The web UI | [client/AGENTS.md](client/AGENTS.md) |
| `extension/` | The browser extension (Edge, Chrome): a side panel on the page you are on | [extension/AGENTS.md](extension/AGENTS.md) |
| `skills/` | Skills: a `SKILL.md` and ready-made scripts per document type | [skills/AGENTS.md](skills/AGENTS.md) |
| `docs/decisions.md` | Why things are the way they are, measured findings, dated | |
| `settings.json` | Every setting. Per machine, not committed | |
| `mcp.json` | MCP servers, standard `mcpServers` format. Per machine, not committed | |
| `.data/` | Everything Atlas generates: `atlas.db`, Strands snapshots, each chat's uploads and workspace | |
| `launched.json` | Written by `atlas start`: what is running, and with which settings | |

