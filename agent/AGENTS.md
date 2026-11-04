# agent/ — the agent library

Everything that decides what the model is given and how a conversation is
stored. The server imports this; this never imports the server.

```
agent/
  config/       settings.py      settings.json schema, LIVE vs RESTART tiers. The only schema.
                paths.py         every path, anchored to the app root (ATLAS_ROOT)
  model/        llamacpp.py      AtlasLlamaCppModel: thinking switch, streaming, timings
                sampling.py      build_model, RetryPlan (sampling for a turn)
                server.py        llama-server: its API key, the models folder
  prompt/       system.py        the system prompt: instructions, runtime facts, tool sources
                notes.py         notes for the model only: the clock, a retry's hint
                page.py          the note on a message sent from the extension
  runtime/      factory.py       build_agent(): the one place that calls create_harness
                restore.py       restoring from a Strands snapshot, then re-setting the prompt
                memory.py        long-term memory: off, and why
  safety/       policy.py        ToolPolicy: every check before a tool runs, in one order; TaintTracker
                scope.py         Scope: the workspace and allowed folders; where a path argument lands
                placement.py     locate(): the one rule for relative paths, never outside its folder
                call_paths.py    which paths a call touches; the path rewrites before the checks
                approvals.py     the Approver type
                shell.py         a shell command parsed (tree-sitter-bash): read, write, delete, install, other
                installs.py      the install rules, applied by shell.py to each simple command
                rules.toml       the floor: shell commands refused in every tier (rules.py loads and checks it)
                limits.py        RunLimits: model calls, minutes and repeated calls per message
  recovery/     model_retry.py   LocalModelRetry: model calls that fail or come back empty
                tool_recovery.py ToolFailureRecovery: crashed tools, non-zero exits, giving up
  platform/     windows_shell.py WindowsLocalEnvironment: the shell, stoppable commands
                winpaths.py      path forms (/c/... for the model, C:/... for Python), finding Git Bash
  tools/        manager.py       which built-in and Atlas tools are on
                documents/       create_document, edit_docx, set_cell: markdown.py parses, docx.py,
                                 pdf.py and xlsx.py write, base.py writes atomically, tool.py is the tool
                maths/           calculate / dates: evaluator.py (the safe evaluator), dates.py, tool.py
                reading.py       read_text / read_image: capped, typed reads (the harness `read` is off)
                doc_reading.py   read_pdf / read_docx / read_xlsx: fetch from the ingest store
                page.py          page_read / page_find for the browser extension, via client calls
  ingest/       store.py         the ingest store: parse at upload, one worker, SQLite + FTS5, per-chat ownership
                parse.py         a pdf/docx/xlsx into blocks whose ids the edit tools address
                ocr.py           OCR of scanned pages and pictures (RapidOCR)
  store/        chats.py         ChatStore: the chat tree and display transcripts (SQLite)
                snapshots.py     where Strands writes snapshots; deleting them on edit
  integrations/ mcp/             pool.py (connections, per-tool switches), registry.py (search)
                skills/          catalog.py (which exist), installer.py, requirements.py
  extension/    form_fill.py     fill suggestions from the user's details
                table_export.py  a web page's table as xlsx or csv, no model
  common/       ids.py           sortable ids
                redact.py        credentials in free text (install output), hidden before the UI
agent/cli/
  main.py            argument parsing and the entry point (`atlas`)
  commands.py        atlas start | stop | status | logs | settings
  launcher/          supervisor.py (Launcher: starts, health-checks, supervises, restarts, stops;
                     emits events, prints nothing), services.py (each service's command line),
                     logs.py (per-service parsing; drop / collapse / rewrite rules)
  procs.py           spawning, log capture to .data/logs, killing process trees, the job object
  ports.py           who holds a port; stopping only what Atlas started there
  launched.py        launched.json: what was started, and with which settings
  views/             screen.py (the start screen, Rich Live) and keys.py, dev.py (--dev),
                     plain.py (piped, --raw), base.py (shared)
```

## One turn, end to end

1. `build_agent()` reads the current settings, asks each manager for its part,
   and calls `create_harness(...)`. A **new agent every turn**, so a changed
   LIVE setting applies to the next message with no restart.
2. If the turn has a restore point, the agent is restored from that Strands
   snapshot, and the system prompt is set again *after* the restore (a
   snapshot stores its own prompt, which would otherwise win).
3. The server streams `agent.stream_async(text)`, then saves an immutable
   snapshot (`save_snapshot(is_latest=False)`) and records its id on the turn.

## Settings

`settings.json` is validated by `Settings` (`extra="forbid"`: a typo is an
error, not a silent no-op). Every key is in `TIERS`:

- **LIVE** — read when the next turn's agent is built.
- **RESTART** — baked into the running llama-server or the process (model,
  ports, paths). The backend saves a change to the file but keeps running on
  the values it started with; it applies at the next `atlas start`.
  `changed_restart_keys()` compares the file against `launched.json`'s flat
  `restart_settings` block to say which saved values are not live yet.

A new knob goes into `settings.py` and `TIERS` first, then is read by exactly
one manager. The UI shows unknown keys under Storage → Other automatically; to
give one a label and a control, add it to `client/src/features/settings/schema.ts`.

## The chat tree (`store/chats.py`)

Two tables. `turns` holds a turn's user text, attachments, `before_snap` (the
parent's `after_snap`: where to restore from) and `after_snap` (Strands
snapshot ids), its status, and `render_json` — what the UI showed, which is
**never** given back to the model.

| Action | Rule |
|---|---|
| Send | Under the selected leaf, which must be `completed`. A cancelled or failed turn can be retried or edited, never continued, so a half-finished tool call is never built upon. |
| Retry | **Last turn only.** A sibling with the same parent and restore point. Nothing is deleted. |
| Edit | **Any turn.** The turn, every version of it and everything below are deleted — rows and snapshot files — and the new text runs from the same restore point. |
| `<` `>` | Select another version at that position. Every version keeps its own follow-ups. No snapshot is read. |
| Cancel | The turn keeps its partial transcript and gets no snapshot. |
| Crash | Turns left `running` become `interrupted` at the next start. |

Roots are siblings of each other; `chats.selected_root` plays the role a
parent's `selected_child` plays for every other position.

## What makes a retry different

A retry restores the same state and asks the same question, so on its own a
small model gives a near-copy. `retry.*` settings, applied to retries only:

1. The previous versions' answers are quoted after the question with an
   instruction to take a different approach (`retry_hint`). The note is
   removed from the message before the snapshot is saved, so later turns never
   see it. This is the lever that changes the *approach*.
2. Temperature is raised by `temperature_boost`, `presence_penalty` is set.
3. A fresh random `seed`.

On a factual question, expect different framing, not different facts.

## Recovery (`recovery/`)

Hooks, not prompt text: a 2B model does not reliably follow "retry on failure".

- `LocalModelRetry` subclasses Strands' `ModelRetryStrategy`: retries a model
  call on a transport error, a 5xx or an **empty response**, with a fixed short
  delay instead of exponential backoff (there is no rate limit locally). The
  run is told, so the UI drops the discarded partial output.
- `ToolFailureRecovery`:
  - re-runs a tool that **crashed** (raised), up to `tool_crash_retries`;
  - treats a shell command with a **non-zero exit code** as failed — the
    harness reports it as a success, and the model then says it worked;
  - appends "attempt N of M, read the error, fix the arguments" to a failed
    result, and past the limit "stop and explain";
  - if the model stops right after a failure, resumes it once
    (`AfterInvocationEvent.resume`). The run emits `resumed`, and the answer
    the model gave up with is shown folded away as an earlier attempt.

## The model adapter (`model/llamacpp.py`)

The stock `LlamaCppModel` needed five things:

- `chat_template_kwargs.enable_thinking` is sent explicitly; the base class
  drops unknown request keys and llama-server defaults to thinking on.
- The response is **streamed** (`client.stream`). `client.post` buffered the
  whole body, so each model call arrived in one burst.
- `timings` (per token) go to an observer: the context meter and tokens/s.
- `reasoningContent` blocks are sent as each assistant message's
  `reasoning_content`, not as content (the base formatter raises on them).
  Gemma's template keeps the current turn's reasoning and drops older turns'
  by itself; stripping it all made the model forget its plan after every tool
  call and repeat its steps.
- `document` blocks (a pdf/docx/xlsx some tools return)
  become a text note pointing at the skill; llama-server answers them with a 400.

## Documents (`tools/documents/`)

The model writes **Markdown**; `create_document` turns it into docx
(python-docx), pdf (reportlab) or xlsx (openpyxl: every Markdown table becomes
a sheet named after the heading above it; CSV or TSV lines work too). Every
file is written to a temp file, reopened by its own library to prove it
parses, and only then moved into place. A failure returns an *error* tool
result in words the model can act on, so `ToolFailureRecovery` counts it.

`edit_docx` replaces one paragraph or table cell, by the id `read_docx`
printed (`b12`, `t1.r3.c3`); `set_cell` sets one cell (`Mar!B2`), a number as
a number and text starting `=` as text (blocks.py). Both work only on a
version of the file this chat attached or read, and re-ingest it after. A PDF
cannot be edited in place. `create_document` never replaces a file: an
existing name gets `-2`, so a failed edit cannot turn into a regenerated copy
over the original.

**These tools come with skills** (`runtime/skill_tools.py`): loading the pdf,
docx or xlsx skill registers its writing tools (`SKILL_TOOLS`), effective from
the next model call. The skills plugin keeps the loaded skills in the agent's
state, saved with each snapshot, so later turns are built with the same tools,
always in `SKILL_TOOLS` order (the list is part of llama.cpp's cached prefix).
A call to one before its skill is loaded is answered "load the docx skill".

The policy's documents step refuses the plain `write`/`edit` tools on
.docx/.xlsx/.pdf/.pptx (writing text into one is how corrupt documents
happened). `read_text` answers a pdf/docx/xlsx with the tool that reads it.

Images: ingest saves a document's images in the store and the readers print
each as `![caption](asset:<sha12>/<file>)`. `create_document` embeds such
lines in docx and pdf, so a rewrite keeps its figures; an `asset:` image
resolves only for a chat that owns the document. Images that cannot be
found are left out and named in the result.

## Reading documents (`ingest/`, `tools/doc_reading.py`)

**Ingest is not reading.** An upload or import submits the file to the
store (`store_for(data_dir)`), which returns at once; one worker thread
parses it into blocks in `<data>/parsed/index.db`, images under
`<data>/parsed/<sha>/`. A PDF's text layer is published first (`partial`),
then each scanned page as OCR finishes, pages a read waits for first. The
read tools only fetch: they wait briefly for pages in progress and never
parse. Every write is a transaction; an interrupted PDF resumes at the next
submit.

Entries are shared by content hash but owned per chat (`owners`), written
when the chat attaches or reads the file, after the policy's access check.
Deleting a chat drops its ownership and every entry nobody else owns.
`read_pdf` downloads an https link into the workspace and taints the chat;
it refuses `file://`, which would slip past the access check.

Block ids are the edit tools' addresses: `p27.3` (pdf), `b12` and `t1`
(docx body paragraph and table; a cell is `t1.r3.c3`), `Mar!A1:C51` (xlsx).

## Arithmetic and dates (`tools/maths/`)

`calculate("3940 + 824.82 + 1895.5")` and `dates('days_between("2 Oct 2026",
"15 Nov 2026")')` each take **one string**, so the model never picks an
operation or counts arguments: it writes the sum it would have written in its
answer, and code works it out. Parsed with `ast` and evaluated from an
allow-list (numbers, quoted dates, `+ - * / // **`, a few named functions);
nothing is executed. Numbers are `Decimal`, so money is exact. The docstrings
carry examples, which a 2B model copies. Nothing yet forces their use.

Atlas's own tools (these two, the document tools and the read tools) are switched one by one
in `tools.atlas` (Settings > Agent > Built-in tools); `ToolManager.atlas_tools()`
resolves them. An older `tools.documents` switch still loads.

## Tool policy (`safety/policy.py`)

Every check made before a tool runs is one `ToolPolicy` hook with ordered
steps. The first step that refuses sets `cancel_tool` and the rest are skipped:

1. **normalise**: paths in the form each tool takes. MCP arguments get Windows
   paths (`/c/Users/x` -> `C:/Users/x`) and relative paths placed by `locate`;
   `write`/`edit` get `/c/...` for a pasted `C:\...`; unquoted `C:\...` in
   a shell command becomes `C:/...` (bash eats the backslashes).
2. **floor**: refused outright, no card: Atlas's own files (protected.py), the
   floor's shell rules (rules.toml), and shell writes or deletes that land in
   Atlas's data or another chat (relative paths placed from the workspace).
3. **access**: a path outside the scope asks the user (kind `access`).
3. **install**: a `shell` command that installs asks (kind `install`).
4. **page taint**: once outside content is in the **chat** (the extension's page
   tools, a PDF `read_pdf` downloads, an MCP tool from an untrusted server), shell commands and
   writes outside the workspace ask (kind `page`), in that turn and every later
   one: the content stays in the history. Stored on the chat (`chats.tainted`);
   `TaintTracker` marks it after such a tool returns. An MCP server is trusted
   when Atlas points it only at the allowed folders (`{atlas:folders}`) or it is
   marked `"atlas": {"trusted": true}` in mcp.json.
5. **sensitive**: an MCP tool set to "ask" on the MCP page asks (kind `tool`).
6. **documents**: `write`/`edit` on a binary document is redirected.

Recovery after a tool runs stays in `recovery/`.

### Access

One model for every way the agent reaches a file. The **scope** is the chat
workspace (always), `access.folders` (Settings > Access, subfolders included),
and, read-only, the skills folder and Python install so scripts can be read.
What is checked:

- the read tools, `write`, `edit`, `create_document`, `edit_docx`, `set_cell`: an absolute
  `path` argument. A relative path is placed by `safety/placement.locate`: the
  workspace first, then each allowed folder (an existing file wins; a new
  one goes where its folder exists). The filesystem MCP server, the skill
  scripts (`$ATLAS_FOLDERS`) and the read tools follow the same rule, so
  `Demo/Invoices/x.pdf` means one file to every tool.
- `shell`: absolute drive paths in the command (`/c/...`, `C:/...`, `C:\...`,
  quoted or bare). `/tmp` and other POSIX paths are the shell's own.
- MCP tools: any string argument that is a drive path.

Outside the scope the user gets an Allow / Deny card naming the folder. Allow
holds for that folder for the rest of the turn, for what was asked: a read
grant does not allow writes, and at a drive root or the home folder only the
exact path is granted (never all of `C:/`). With `access.ask_outside` off
it is refused, and the model is told the user can add the folder in Settings.

MCP servers get the same folders through their arguments: `{atlas:folders}` in
a server's `args` expands to the chats folder plus each existing allowed
folder. Strands' `MCPClient` does not implement the MCP roots protocol, so
arguments are the only way in. Changing the folders reconnects those servers.
The shell check is a guard against mistakes, not a sandbox: a script can open
any path it builds itself.

### Approvals

Steps call `approver(kind, detail)`. The run emits `approval_request`, the UI
shows Allow / Deny, and no answer within `approvals.timeout` seconds (60)
counts as Deny, as does cancelling the run. The model is then told not to try
another way. Python packages are installed with `python -m pip`, so they land
in Atlas's own venv.

### Skill requirements (`integrations/skills/requirements.py`)

Read from `requirements.txt`, `package.json` dependencies, and install commands
in SKILL.md code fences (`npm install -g x`, `pip install y`), each with its
installed status. The Skills page lists them and installs the missing ones.
That click is the approval; the model never has to.

## Windows (`platform/`)

- Every shell command starts in the **chat's workspace**, `$ATLAS_SKILLS`
  points at the skills folder and `$ATLAS_FOLDERS` lists the allowed folders. An attached file is named by its name alone
  (`"exp4.pdf"`), and the bundled `SKILL.md` commands are
  `python "$ATLAS_SKILLS/pdf/scripts/merge_pdf.py" ...`. The attachment
  list gives each file's exact read call.
- **Stop ends a running command.** Strands stops a turn only at its safe
  points, and a running shell command is not one. The environment watches the
  agent's cancel signal (set on it in `build_agent`) and, on Stop or timeout,
  kills the command's whole process tree (`taskkill /T`: killing `sh.exe`
  alone left the Python script it ran going).
- Commands run through Git Bash when it exists (`cmd.exe` as a fallback); the
  venv's `Scripts` is first on PATH, so a bare `python` is the project's.
- The model is shown every path as `/c/Users/...` (`model_path`). That one form
  works unquoted in bash, as an argument to `python.exe` (MSYS converts it),
  and in the harness file tools, which reject any path not starting with `/`.
  `_resolve_path` turns it back into `C:/Users/...` for Python's file calls.
  Other POSIX paths (`/tmp/...`) are
  resolved with Git's `cygpath`.
- Strands' default callback handler printed every token to the console; under
  a cp1252 console an emoji failed the run. It is off (`callback_handler=None`)
  and the backend and every skill script run in UTF-8 mode.

## Skills and MCP

- **Skills** (`integrations/skills/catalog.py`): every folder under `skills/` with a
  `SKILL.md` is on unless listed in `skills.disabled`. The harness gets the
  list of enabled folders. Front matter is parsed as YAML. Installed skills
  carry `.atlas-source.json`; folders without one shipped with Atlas and can
  be switched off but not deleted. See [skills/AGENTS.md](../skills/AGENTS.md).
- **MCP** (`integrations/mcp/pool.py`): `mcp.json` in the standard format. Each enabled
  server is connected **once per process** and kept open by a permanent pool
  consumer; each turn gets the individual tool objects. A per-tool switch is
  stored as the server's standard `tool_filters.rejected` and applied when the
  turn's tool list is built, so switching needs no reconnect. Every tool schema
  costs prompt tokens on every request; the manager estimates them.
- **MCP lifecycle.** Servers start side by side. A start is bounded by
  `mcp.startup_timeout` and cancellable (`_start_bounded`): Strands' own
  timeout cannot stop a server that never answers `initialize` (its `stop()`
  waits forever and the process lives on), so Atlas cancels the client's
  background tasks itself, which ends the server's process tree. Refresh, a
  settings change and shutdown all cancel a start in progress and wait for it
  before anything new starts: one copy of a server at a time, because two
  copies fight over the same things (uv's cache lock, a port).
- **Where tools come from.** Each MCP tool's description starts with
  `[MCP: <server>]`, and the prompt lists tools grouped by source (built in,
  skills, each MCP server). Without that, asked to use an MCP tool, the model
  used the built-in one with the same purpose.

## Memory

Off, enforced by validation. The harness memory store is a flat folder with no
chat or branch in its key, injected every turn, so a fact from one version of a
chat leaks into every other. Turning it on needs a design (scope per chat or
per branch), not a flag. `runtime/memory.py` sets all four switches it takes to
keep it, and its tools, out of the request.

## Checking it

`python tests/check.py` runs every offline check (ruff, pyright, pytest, and
the TypeScript checks); CI runs the same on every push. The real-model checks
(`tests/bench.py`, `tests/live/`) need the GPU and are run by hand at every
checkpoint. See [tests/README.md](../tests/README.md).
