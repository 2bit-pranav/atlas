# Architecture

How Atlas works today. Why it works this way is in [docs/decisions.md](docs/decisions.md);
module-by-module detail is in each folder's `AGENTS.md`.

```
 browser (web UI)  ─┐
 Edge side panel   ─┴─► FastAPI backend (server/) ──► agent library (agent/) ──► llama-server (llama.cpp)
                          runs, chat tree, SSE          Strands harness, tools,      Gemma E2B, one slot,
                          approvals, traces             guardrails, ingest store     per-launch API key
```

Three processes, all on 127.0.0.1, started and supervised by `atlas start`
(`agent/cli/`): llama-server, the backend (which also serves the built web UI),
and in `--dev` a Vite server. Everything Atlas writes goes in `.data/`.

## A turn, end to end

1. **Send.** `POST /chats/{id}/messages` checks the run slot (one run at a time),
   inserts the turn under the chat's leaf and starts a `Run` (`server/runs.py`).
   The client shows the message at once and follows `GET /runs/{id}/events` (SSE).
2. **Build.** `server/state.py::execute` calls `build_agent()`
   (`agent/runtime/factory.py`), the only place that calls `create_harness`. A new
   Strands agent every turn, from the current settings: the tools (typed file,
   document and web tools; writing tools if the message names a document type),
   the system prompt, the hooks (below), and the session manager.
3. **Restore.** The agent is restored from the parent turn's snapshot (an
   immutable file, always named), then its system prompt is set again: a
   snapshot's stored prompt would otherwise win.
4. **Stream.** `agent.stream_async(text)`. Strands loops: model call, tool calls,
   model call, until the model stops calling tools. Every event is translated
   (`server/events.py`), folded into the turn's display transcript
   (`server/transcript.py`), streamed to the client and written to the run's
   trace (`agent/common/trace.py`, one JSONL line per record, with the exact body of
   every model request and response).
5. **Hooks decide.** Before each tool call: limits, the egress gate, the tool
   policy (which may pause the run on an approval card the user answers). After:
   failure recovery, the input fence. At the end: the done check and the
   provenance rail may send the turn back once with what is missing.
6. **Finish.** A completed turn saves a new snapshot (`is_latest=False`) and its
   render; a cancelled or failed one keeps its render and no snapshot, so it can
   only be retried or edited. Files the turn made or changed are listed as chips.

A retry is a sibling turn from the same restore point, with the earlier answers
quoted and sampling widened; an edit deletes that turn and everything after it,
rows and snapshots, never files. The chat tree is `turns` in `.data/atlas.db`.

## Inference and the prompt cache

- **One model, one slot.** llama-server runs the model chosen in Settings
  (`-m`, `--mmproj` for vision/audio, `-c 32768`, flash attention, `-np 1`).
  Switching models is a restart. Capabilities come from the GGUF headers
  (`agent/model/gguf.py`).
- **The adapter** (`agent/model/llamacpp.py`) streams, always sends
  `enable_thinking` (the composer's toggle), passes the current turn's reasoning
  back as `reasoning_content`, and reports llama's `timings` for the context
  meter and per-call stats.
- **KV cache.** llama.cpp reuses the longest prefix shared with the previous
  request (`cache_prompt`). Atlas keeps that prefix stable: the system prompt has
  only the date (the time is appended to each user message), tools are
  registered in a fixed order, and no chat id or workspace path appears in it.
  So only a new chat's first call reads the ~4.8k-token prefix; every later call
  reads just what is new. Questions asked by code (below) go through the same
  slot, and llama.cpp keeps the chat's prompt cached across them.
- **Context.** Near the window (75% of 32k), earlier turns' tool results are
  replaced by a one-line stub, oldest first, down to 50%
  (`agent/runtime/context.py`). Answers are never touched; nothing is summarised.
- **Limits.** 40 model calls, 15 minutes and 3 identical tool calls per message
  (`agent/safety/limits.py`); past one, the turn ends with a message.

## Documents: ingest, then code pipelines

**Ingest** (`agent/ingest/`). An upload, an import or a read submits the file
to one store: a worker parses it into addressable blocks in SQLite with FTS5
(`.data/parsed/index.db`), keyed by content hash and owned per chat. A PDF's
text layer is published first, scanned pages as RapidOCR finishes them (pages a
read waits for first). A background index keeps the documents in the allowed
folders in the store, text layer only, so `find_files` finds them by content.

**Reading** is fetching from the store: `read_pdf`, `read_docx`, `read_xlsx`,
`read_text` return capped, searchable slices with block ids (`p3.2`, `b12`,
`t1.r3.c2`, `Mar!A1:C41`) and say what they left out. SQL over a sheet or CSV
runs in DuckDB with file access sealed.

**Writing** comes with the pdf, docx and xlsx skills. `create_document` turns
Markdown into docx, pdf or xlsx, filling `{{file#t1}}`, `{{file!A1:C9}}` and
`{{file sql: ...}}` references from the files themselves; every file is written
to a temp path, reopened to prove it parses, then moved, and never over an
existing one. `edit_docx` and `set_cell` change one block or cell by address.

**Deterministic pipelines** (`agent/tools/pipelines.py`), for work with a known
shape. Code loops; the model answers one schema-constrained question per unit
through `ModelCall` (`agent/runtime/model_call.py`, which honours Stop, the
limits and the trace); code checks every value against its source and builds
the file:

| tool | unit | check |
|---|---|---|
| `extract_table(files, columns, path, total)` | one file | each value appears in that file; total added with `Decimal` |
| `write_summary(file, path)` | one section | every number appears in its section; asked once more, else left out |
| `compare_documents(old, new, path)` | one change (difflib) | a description's numbers appear in the old or new text |
| `fill_template(template, path, details)` | one template | each value appears in the user's details |

Fill (web forms) and Key moments (videos) in the extension use the same
`ModelCall`. Skill scripts (merge, split, convert) run through `run_skill`: an
argv list with the venv's Python, no shell, outputs never over an existing file.

## The guardrail pipeline

Every check is code; none calls a model, so none adds time before the first
token. Each verdict is written to the run's trace.

```
tool call ─► limits ─► EGRESS ─► ACTION (ToolPolicy) ─► tool runs ─► INPUT fence ─► model
                                                                  ...end of turn ─► OUTPUT rail
```

1. **Egress** (`agent/safety/egress.py`), before the policy so a refusal never
   shows a card. Every string about to leave the machine (`web_search` queries,
   `read_url` addresses, PDF links, `run_skill` links, untrusted MCP arguments):
   no file paths or long numbers, at most 600 characters a turn once the chat is
   tainted, no run of 12 words copied from a document the chat read.
2. **Action** (`agent/safety/policy.py`, ordered steps, first refusal wins):
   - *normalise* paths into the form each tool takes;
   - *floor*: Atlas's own files, other chats and `rules.toml` commands are refused
     outright, in every mode;
   - *documents*: plain text writes into a .docx/.xlsx/.pdf are redirected;
   - *grid* (`grid.py`): the call as (place, action) pairs (workspace, folders,
     elsewhere, system, upload × read, create, change, delete, run) looked up in
     the mode's grid (look, ask, work); attached files ask before change or
     delete; once the chat is tainted, every run, change and delete asks;
   - *install* and *sensitive* steps ask for installs and for tools set to Ask.

   An approval card pauses the run until the user answers (60 s is Deny).
3. **Input** (`agent/safety/rails.py`). Every tool result carrying outside text
   (files, pages, web, MCP) is wrapped in `<untrusted source=...>`, which the text
   cannot close. Text addressed to the assistant ("note to the AI assistant",
   "ignore previous instructions", ...) taints the chat, gets a warning inside the
   fence, and shows the user a notice. The UI shows results without the fence.
4. **Output** (`agent/safety/provenance.py`). Figures the model typed into a
   document must appear in a message or a tool result (references, filled by
   code, are exempt). A document with unsourced figures sends the turn back once;
   what remains, and unsourced figures in a tool-using answer, become a notice.

Outside the agent: the extension's token opens only its routes and only as a
header; llama-server needs the per-launch key; images in answers are never
loaded; Exa fetches web pages, never this machine.

## The browser extension

A WXT Edge extension (`extension/`). The side panel sends the open page with
each message: Google Docs, Sheets and Slides through their exports, articles
through Readability, anything else as an accessibility tree with element refs.
Page tools (`page_read`, `page_find`, `page_show`) run in the tab through the
run (`client_call`, like an approval). Answers point at the page by quote or
ref, highlighted by code. Fill suggests form values from the user's details
(never submits), offers local files as drag-in cards for upload fields, and Key
moments turns a video's chapters or transcript into play-from-here rows.
