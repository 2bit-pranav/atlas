# Atlas

A local AI agent for your own documents, folders and browser, built for small
models (2-7B) on a laptop GPU. No cloud: the model runs in llama.cpp on your
machine, and nothing leaves it except web searches you allow.

- **Inference:** `llama-server` (llama.cpp) runs a `.gguf` model such as Gemma E2B.
- **Agent:** the [Strands](https://strandsagents.com) harness owns the agent
  loop, tools, skills, MCP and history; Atlas configures it and adds a chat tree
  with versions, runs that outlive the browser, typed document tools, code-driven
  pipelines, a permission grid and guardrails, an HTTP API and a web UI.
- **UI:** a React web app, and an Edge side panel that works on the page you are on.

How it works: [ARCHITECTURE.md](ARCHITECTURE.md). Why: [docs/decisions.md](docs/decisions.md).
Measured progress: [benchmarks/BENCHMARKS.md](benchmarks/BENCHMARKS.md).

## Install (Windows)

Needs Python 3.14, Node 20+ (to build the UI once), and llama.cpp
(`winget install ggml.llamacpp`, which provides `llama serve`).

```
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.lock.txt -r skills/pdf/requirements.txt ^
    -r skills/docx/requirements.txt -r skills/xlsx/requirements.txt
.venv\Scripts\pip install -e . --no-deps          # provides the `atlas` command
copy settings.example.json settings.json
```

Put a model in `llm/`, one folder each with its `.gguf` (and an `mmproj` file for
images and audio), e.g. `llm/gemma/`, and set `model.name` in `settings.json`
to the folder's name (or pick it later under Settings > Model).

## Running it

```
atlas start                      # the model, the backend and the web UI, at http://127.0.0.1:8000
atlas stop                       # stops everything, one line per service
atlas status                     # what is running, on which ports, since when
atlas logs [llama|backend|web]   # the full logs (-f to follow, -n N lines)
atlas trace [RUN] [--prompt N]   # what a run did: each model call, tool and policy decision (default: the newest)
atlas replay RUN [--call N]      # send a run's model call again and compare the answer
atlas settings check             # validate settings.json
```

`atlas start` shows a small live panel (o opens the UI, l shows logs, r
restarts, q stops). The backend serves the built UI, so day-to-day use needs no
Node once it is built; `atlas start` builds it if `client/dist` is missing and
rebuilds it when its sources have changed. `--dev` runs Vite
with hot reload (UI at :5173); `--raw` prints every log line; `--no-llama`,
`--no-backend` and `--no-client` start a subset. Logs are in `.data/logs/`.

Never start the backend with `uvicorn --reload`: on Windows its worker cannot
start subprocesses, so every script fails with an empty error.

Optional: an [Exa](https://exa.ai) key under Settings > Agent turns on web
search; the browser extension is in `extension/` (see its AGENTS.md to build and load it).

## Example: invoices into a spreadsheet

1. **Settings > Access:** add the folder that holds your invoices, e.g.
   `C:\Users\you\Downloads`. Atlas can read it; changing or deleting anything
   there asks you first. Atlas's own data and other chats are never reachable.
2. **New task:** *"Make invoices.xlsx from the invoices in my Downloads: invoice
   number, vendor, date and amount due, and tell me the total."*
3. Atlas finds the PDFs (`find_files`) and calls `extract_table` once. Code
   reads each invoice, asks the model one question per file, checks every value
   against that file's text, adds the total itself, and writes the workbook.
   Values that could not be checked are left empty and named.
4. The work panel shows each step ("Found 12 files", "Made invoices.xlsx"); the
   file appears as a download under the answer, with the total in the reply.
   About 20 s for 12 invoices on a 4 GB laptop GPU.

The same shape works for *"Write summary.docx: a one-page summary of review.pdf"*
(`write_summary`, section by section), *"What changed between contract_v1.docx and
contract_v2.docx?"* (`compare_documents`) and *"Fill in offer.docx from my
details"* (`fill_template`). In Edge, the side panel answers about the page you
are on, fills Google Forms from your details (you click Apply; it never submits)
and lists a video's key moments.

## Where things are

| Path | What | Read |
|---|---|---|
| `agent/` | The agent library: settings, the agent factory, the model adapter, tools, safety, the ingest store, the CLI | [agent/AGENTS.md](agent/AGENTS.md) |
| `server/` | FastAPI: runs, the event stream, the HTTP API | [server/AGENTS.md](server/AGENTS.md) |
| `client/` | The web UI | [client/AGENTS.md](client/AGENTS.md) |
| `extension/` | The Edge/Chrome side panel | [extension/AGENTS.md](extension/AGENTS.md) |
| `skills/` | Skills: a `SKILL.md` and ready-made scripts per document type | [skills/AGENTS.md](skills/AGENTS.md) |
| `tests/` | Offline checks (`tests/check.py`) and the live suite (`tests/live/suite.py`) | [tests/README.md](tests/README.md) |
| `benchmarks/` | Measured runs of the live suite | [benchmarks/BENCHMARKS.md](benchmarks/BENCHMARKS.md) |
| `docs/decisions.md` | Why things are the way they are | |
| `settings.json` | Every setting. Per machine, not committed | |
| `mcp.json` | MCP servers, standard `mcpServers` format. Per machine, not committed | |
| `.data/` | Everything Atlas generates: `atlas.db`, snapshots, traces, each chat's files, the parsed documents | |
