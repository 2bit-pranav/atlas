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
atlas start                      # llama-server :8080, backend :8000, web UI :5173
atlas stop                       # stops all three and checks the ports are free
```

Models live in `llm/`, one subfolder each with its `.gguf` (and an `mmproj`
file for image input): `llm/gemma/`. Pick one under Settings > Model and
press Restart in the sidebar; llama-server and the backend restart with it.

`atlas start --no-llama`, `--no-backend` and `--no-client` start a subset.
`atlas settings check` validates `settings.json`; `atlas settings show
--restart-required` lists saved settings the running servers do not have yet.

Open http://127.0.0.1:5173. Ports come from `settings.json` and nowhere else.

Do not start the backend with `uvicorn --reload`: on Windows its worker runs
an event loop that cannot start subprocesses, so every shell call and every
skill fails with an empty error. `atlas start` never uses it.

## Where things are

| Path | What | Read |
|---|---|---|
| `agent/` | The agent library: settings, the agent factory, the model adapter, the chat tree, skills, MCP, the CLI | [agent/AGENTS.md](agent/AGENTS.md) |
| `server/` | FastAPI: runs, the event stream, the HTTP API | [server/AGENTS.md](server/AGENTS.md) |
| `client/` | The web UI | [client/AGENTS.md](client/AGENTS.md) |
| `skills/` | Skills: a `SKILL.md` and ready-made scripts per document type | [skills/AGENTS.md](skills/AGENTS.md) |
| `docs/decisions.md` | Why things are the way they are, measured findings, dated | |
| `settings.json` | Every setting. Per machine, not committed | |
| `mcp.json` | MCP servers, standard `mcpServers` format. Per machine, not committed | |
| `.data/` | Everything Atlas generates: `atlas.db`, Strands snapshots, each chat's uploads and workspace | |
| `launched.json` | Written by `atlas start`: what is running, and with which settings | |

## The rules that shape everything

1. **Use Strands; do not rebuild it.** If the harness or SDK does something,
   Atlas configures it rather than reimplementing it.
2. **Strands owns the model's history.** Atlas stores the shape of a chat
   (which turn follows which, which version is selected) and the snapshot ids
   to restore, plus a display copy of each answer. It never feeds its own copy
   back to the model.
3. **Nothing is parsed at upload.** Files are saved; the model reads them on
   demand through skills.
4. **A small model gets ready-made tools, not instructions to write code.**
   Skills ship scripts. Recovery from failures is code (Strands hooks), not a
   sentence in the system prompt.
5. **Measure, then write it down.** A surprising behaviour goes into
   `docs/decisions.md` with what was observed, so nobody rediscovers it.
