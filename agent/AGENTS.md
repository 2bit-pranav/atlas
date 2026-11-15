# agent/ — the agent library

Everything that decides what the model is given, what it may do, and how a
conversation is stored. The server imports this; this never imports the server.
How a turn flows through it end to end is in [ARCHITECTURE.md](../ARCHITECTURE.md);
why, in [docs/decisions.md](../docs/decisions.md).

```
agent/
  config/       settings.py      settings.json schema (strict), LIVE vs RESTART tiers. The only schema
                paths.py         every path, anchored to the app root; generated state in .data/
  model/        llamacpp.py      the Strands model adapter: streaming, thinking flag, reasoning, timings
                sampling.py      build_model: sampling per turn, a retry's widening
                server.py        llama-server: its per-launch key, the models folder, capabilities
                gguf.py          what a model can do, from its GGUF headers (capped reads)
  prompt/       system.py        the system prompt: date, folders, tool sources, the fence's meaning
                notes.py         notes for the model only: the clock, a retry's hint
                page.py          the page sent from the extension, fenced
  runtime/      factory.py       build_agent(): the one place that calls create_harness
                restore.py       restore a snapshot, then set the prompt again
                model_call.py    ModelCall: one schema-constrained question asked by code
                skill_tools.py   writing tools registered with their skill; preload by message
                context.py       TrimToolResults: earlier tool results stubbed near the window
                memory.py        long-term memory: the four switches that keep it off
  safety/       policy.py        ToolPolicy (normalise, floor, documents, grid, install, sensitive); TaintTracker
                grid.py          (place, action) -> run / ask / refuse, per mode; shell_reads
                rails.py         Rail/run_rails; the input fence (untrusted()); instruction detection
                egress.py        EgressGuard: everything that leaves the machine
                provenance.py    every typed figure needs a source
                scope.py         the workspace, folders, uploads; Scope.place (where a path lands)
                placement.py     locate(): the one rule for relative paths
                call_paths.py    which paths a call touches (TOOL_ACTIONS, pipeline and run_skill inputs)
                shell.py         a command parsed with tree-sitter-bash: read, write, delete, install, other
                installs.py      install rules; rules.toml + rules.py: the floor; protected.py: Atlas's files
                limits.py        RunLimits: model calls, minutes, repeats (also charged by ModelCall)
                approvals.py     the Approver type
  recovery/     model_retry.py   LocalModelRetry: transport errors, 5xx, empty responses; fixed delay
                tool_recovery.py ToolFailureRecovery: crashes, non-zero exits, resume after giving up
                done_check.py    DoneCheck: a broken or missing file, an announced step, a half-read summary
  tools/        manager.py       which built-in and Atlas tools are on (ATLAS_TOOLS order is fixed)
                reading.py       read_text, read_image (capped; copy hints for CSV)
                doc_reading.py   read_pdf, read_docx, read_xlsx from the ingest store; sealed DuckDB SQL
                documents/       create_document (markdown.py parses, references.py fills {{...}},
                                 docx/pdf/xlsx write, base.py atomic), edit_docx, set_cell (blocks.py)
                pipelines.py     extract_table, write_summary, compare_documents, fill_template
                skills_run.py    run_skill: a skill's script as an argv list, no shell
                files.py         delete_file (Recycle Bin), copy_file, move_file (never over a file)
                finding.py       find_files (name, folder, content via the store), list_folder
                web.py           web_search, read_url through Exa
                page.py          page tools for the extension, through client calls
                maths/           calculate, dates: an allow-list evaluator, Decimal
  ingest/       store.py         SQLite + FTS5 blocks, one worker, per-chat ownership, text-only entries
                parse.py         pdf/docx/xlsx into addressable blocks; ocr.py: RapidOCR
                indexer.py       FolderIndex: the allowed folders kept in the store, text layer only
  store/        chats.py         the chat tree and display transcripts; snapshots.py: Strands snapshots
  integrations/ mcp/             pool (connections, per-tool switches), registry, secrets
                skills/          catalog, installer, requirements
  extension/    form_fill.py     Fill: one ModelCall; profile.md; basket.py: files for upload fields
                moments.py       Key moments: chapters, else one ModelCall; table_export.py: no model
  platform/     windows_shell.py the shell environment: Git Bash, stoppable commands, no secrets
                winpaths.py      path forms (/c/... for the model, C:/... for Python)
  common/       trace.py         a run's trace on disk; ids.py; redact.py (credentials hidden in logs)
agent/cli/      main.py, commands.py (atlas start|stop|status|logs|settings), tracing.py (trace, replay),
                launcher/ (supervisor, services, logs), procs.py, ports.py, launched.py, views/
```

## Settings

`settings.json` is validated by `Settings` with `extra="forbid"`: a typo or a
removed key is an error naming the key, not a silent no-op. When a key is
removed, the settings files are edited to match; there is no migration code.
Every key is in `TIERS`:

- **LIVE**: read when the next turn's agent is built (a new agent every turn).
- **RESTART**: baked into llama-server or the process (model, ports, paths,
  context size). Saved to the file at once, applied at the next `atlas start`.

A new key goes into `settings.py` and `TIERS`, then is read in exactly one
place. The UI shows unknown keys under Storage → Other; to place one, add it to
`client/src/features/settings/schema.ts`.

## The chat tree (`store/chats.py`)

| Action | Rule |
|---|---|
| Send | Under the selected leaf, which must be `completed`. |
| Retry | Last turn only: a sibling from the same restore point, earlier answers quoted, sampling widened. Nothing deleted. |
| Edit | Any turn: it, its versions and everything below are deleted (rows and snapshots), never the files they made. |
| `<` `>` | Select another version; each keeps its own follow-ups. No snapshot read. |
| Cancel | Partial render kept, no snapshot. |
| Crash | `running` turns become `interrupted` at the next start, shown from their trace. |

## Tools and skills

Reading needs no skill. Loading the pdf, docx or xlsx skill registers its
writing tools (`SKILL_TOOLS` in `tools/documents/tool.py`), effective from the
next model call; a message that names a document type, or attaches one, starts
the turn with them (`skill_tools.for_message`). The skills plugin keeps loaded
skills in the agent's state, so later turns are rebuilt with the same tools.
Atlas's tools are switched one by one in `tools.atlas`; `tools.builtin` has the
harness's `write`, `edit` and `shell` (off).

## Non-Obvious Invariants & Footguns

**The model and the harness**
- **Memory needs all four switches off** (`runtime/memory.py`): `memory`,
  `context_manager`, `background_tasks`, `builtin_plugins=[]`. Any one left on
  brings a tool or a cross-branch leak back. `test_harness_contract.py` checks it.
- **Never write `snapshot_latest`** (`save_latest_on="trigger"`): Strands restores
  it automatically, so a first message would start with another conversation.
- **Set the system prompt again after every restore**, with the harness's own
  builder; the snapshot's stored prompt wins otherwise.
- **The prompt prefix must stay stable within a day** for llama.cpp's cache: no
  time of day, chat id or workspace path in the system prompt; tools always
  registered in the same order (`ATLAS_TOOLS`, `SKILL_TOOLS`).
- **Pass the current turn's reasoning back** (`reasoning_content`); stripping it
  made the model lose its plan after every tool call. Read reasoning from the raw
  stream event only: it arrives twice.
- **`enable_thinking` must be sent on every request**; llama-server defaults to on.
- **`callback_handler=None`**: Strands' printer failed runs on a cp1252 console.

**Hooks**
- **Order matters, and after-hooks run in reverse.** `InputFence` is registered
  first so it wraps results last (the done check reads raw results); `EgressGuard`
  sits before `ToolPolicy` so a refusal never shows a card; `Provenance` sits
  before `DoneCheck` so it runs after it and never sends a turn back twice.
- **A tool failure must be an error result** (`{"status": "error", ...}`); text
  saying "Error" is a success to Strands, and recovery never sees it.
- **Each send-back is once per turn.** A new reason to resume goes into an
  existing check, not a second resume.

**Files and documents**
- **Never replace a file.** `create_document`, the pipelines, `copy_file`,
  `move_file` and skill outputs take a free name; only a draft the same turn
  made may be made again (`documents/tool._free`).
- **Every binary document is written atomically and reopened before it is moved
  into place** (`documents/base._atomic`); a failure leaves the old file.
- **DuckDB is sealed** (`_seal`) after loading a sheet or CSV: its own readers
  could open any file on the disk.
- **The model never sees the workspace path**; workspace files are named bare and
  `$ATLAS_WORKSPACE` names the folder. A garbled chat id once landed in another
  chat's folder.
- **Paths for the model are `/c/Users/...`**: unquoted backslashes are escapes in
  bash, and the harness file tools reject paths not starting with `/`.

**Safety**
- **Every path a call touches must reach the policy**: a new tool that reads or
  writes a file adds itself to `call_paths.TOOL_ACTIONS` (and `PIPELINE_INPUTS`
  for inputs), or the floor and grid never see it.
- **A new tool's result is fenced by default** (`rails.OWN_WORDS` lists the
  exceptions, which must be Atlas's own words, never outside text).
- **The floor checks its own examples at load**; a rule that stops matching fails
  the start on purpose.
- **Atlas's data folder and other chats are refused to every tool**, reads
  included, whatever the mode or grants.

**Windows**
- **The venv's `Scripts` goes first on PATH** for every subprocess, or a bare
  `python` is the system's and the model `pip install`s into user site-packages.
- **Stop must kill the process tree** (`taskkill /T`): killing `sh.exe` left the
  Python script it ran going.
- **`CreateProcess` resolves executables from the calling process's PATH**, so
  PATH is changed in `os.environ`, not `env=`; `PROGRAMFILES(X86)` is not a valid
  POSIX name and is filtered; bash needs a `:`-separated PATH.
- **A busy port reports `WinError 10013`**, which reads like a permissions error.
- **Port sweeps only touch processes this launch started**, and only ones that
  look like that service.
