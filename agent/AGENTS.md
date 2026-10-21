# agent/ — the agent library

Everything that decides what the model is given and how a conversation is
stored. The server imports this; this never imports the server.

```
agent/core/
  settings.py        settings.json schema, LIVE vs RESTART tiers. The only schema.
  paths.py           every path, anchored to the app root (ATLAS_ROOT)
  agent_factory.py   build_agent(): the one place that calls create_harness
  model.py           AtlasLlamaCppModel: thinking switch, streaming, timings
  resilience.py      LocalModelRetry, ToolFailureRecovery (Strands hooks)
  documents.py       create_document / edit_document: Markdown -> docx, pdf, xlsx
  policy.py          ToolPolicy: every check before a tool runs, in one order
  page_tools.py      page_read / page_find for the browser extension, via client calls
  approvals.py       the Approver type and what counts as an install
  skill_requirements.py what a skill needs installed; installing it
  chats.py           ChatStore: the chat tree and display transcripts (SQLite)
  session_manager.py where Strands writes snapshots; deleting them on edit
  tool_manager.py    tools.builtin -> the harness's builtin_tools
  skill_manager.py   which skills exist and which the agent gets
  skill_installer.py install from skills.sh / GitHub / zip; delete
  mcp_manager.py     MCP connection pool, per-tool switches, registry search
  memory_manager.py  long-term memory: off, and why
  shell_env.py       WindowsLocalEnvironment: the shell and file paths on Windows
agent/cli/
  main.py            atlas start | stop | status | logs | settings
  launcher.py        starts, health-checks, supervises, restarts, stops; emits events, prints nothing
  screen.py          the start screen (Rich Live, inline)
  views.py           --dev (filtered logs, pinned status line) and plain lines (piped, --raw)
  log_filters.py     per-service parsing and drop / collapse / rewrite rules
  processes.py       spawning, log capture to .data/logs, killing process trees
  launched.py        launched.json, ports, stopping what Atlas started
  launch.py          the command lines, built from settings
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
give one a label and a control, add it to `client/src/lib/settingsSchema.ts`.

## The chat tree (`chats.py`)

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

## Recovery (`resilience.py`)

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

## The model adapter (`model.py`)

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
- `document` blocks (what the harness `read` tool returns for a pdf/docx/xlsx)
  become a text note pointing at the skill; llama-server answers them with a 400.

## Documents (`documents.py`)

The model writes **Markdown**; `create_document` turns it into docx
(python-docx), pdf (reportlab) or xlsx (openpyxl: every Markdown table becomes
a sheet named after the heading above it; CSV or TSV lines work too). Every
file is written to a temp file, reopened by its own library to prove it
parses, and only then moved into place. A failure returns an *error* tool
result in words the model can act on, so `ToolFailureRecovery` counts it.

`edit_document` replaces exact text inside a docx paragraph or table cell, an
xlsx cell, or a text file. A PDF cannot be edited in place; the model is told
to create it again.

The policy's documents step refuses the plain `write`/`edit` tools on
.docx/.xlsx/.pdf/.pptx (writing text into one is how corrupt documents
happened), and answers `read` on one at once with the command that does read it.

Images: the pdf and docx readers save a document's images into a hidden
`.atlas-images/<name>/` folder beside it and print each as `![caption](path)`.
`create_document` embeds such lines in docx and pdf, so a rewrite keeps its
figures. Images that cannot be found are left out and named in the result.

## Tool policy (`policy.py`)

Every check made before a tool runs is one `ToolPolicy` hook with ordered
steps. The first step that refuses sets `cancel_tool` and the rest are skipped:

1. **normalise**: MCP arguments get Windows paths (`/c/Users/x` -> `C:/Users/x`).
2. **access**: a path outside the scope asks the user (kind `access`).
3. **install**: a `shell` command that installs asks (kind `install`).
4. **page taint**: once web-page content is in the turn (the extension's page
   tools), shell commands and writes outside the workspace ask (kind `page`).
5. **sensitive**: an MCP tool set to "ask" on the MCP page asks (kind `tool`).
6. **documents**: `read`/`write`/`edit` on a binary document is redirected.

Recovery after a tool runs stays in `resilience.py`.

### Access

One model for every way the agent reaches a file. The **scope** is the chat
workspace (always), `access.folders` (Settings > Access, subfolders included),
and, read-only, the skills folder and Python install so scripts can be read.
What is checked:

- `read`, `write`, `edit`, `create_document`, `edit_document`: an absolute
  `path` argument (relative paths are the workspace's).
- `shell`: absolute drive paths in the command (`/c/...`, `C:/...`, `C:\...`,
  quoted or bare). `/tmp` and other POSIX paths are the shell's own.
- MCP tools: any string argument that is a drive path.

Outside the scope the user gets an Allow / Deny card naming the folder. Allow
holds for that folder for the rest of the turn. With `access.ask_outside` off
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

### Skill requirements (`skill_requirements.py`)

Read from `requirements.txt`, `package.json` dependencies, and install commands
in SKILL.md code fences (`npm install -g x`, `pip install y`), each with its
installed status. The Skills page lists them and installs the missing ones.
That click is the approval; the model never has to.

## Windows (`shell_env.py`)

- Every shell command starts in the **chat's workspace**, and `$ATLAS_SKILLS`
  points at the skills folder. An attached file is named by its name alone
  (`"exp4.pdf"`), and the bundled `SKILL.md` commands are
  `python "$ATLAS_SKILLS/pdf/scripts/read_pdf.py" "<file>"`. The attachment
  list gives each pdf/docx/xlsx's exact command.
- Commands run through Git Bash when it exists (`cmd.exe` as a fallback); the
  venv's `Scripts` is first on PATH, so a bare `python` is the project's.
- The model is shown every path as `/c/Users/...` (`model_path`). That one form
  works unquoted in bash, as an argument to `python.exe` (MSYS converts it),
  and in the harness file tools, which reject any path not starting with `/`.
  `_resolve_path` turns it back into `C:/Users/...` for Python's file calls.
  Other POSIX paths (`/tmp/...`, which `web_fetch` writes through curl) are
  resolved with Git's `cygpath`.
- Strands' default callback handler printed every token to the console; under
  a cp1252 console an emoji failed the run. It is off (`callback_handler=None`)
  and the backend and every skill script run in UTF-8 mode.

## Skills and MCP

- **Skills** (`skill_manager.py`): every folder under `skills/` with a
  `SKILL.md` is on unless listed in `skills.disabled`. The harness gets the
  list of enabled folders. Front matter is parsed as YAML. Installed skills
  carry `.atlas-source.json`; folders without one shipped with Atlas and can
  be switched off but not deleted. See [skills/AGENTS.md](../skills/AGENTS.md).
- **MCP** (`mcp_manager.py`): `mcp.json` in the standard format. Each enabled
  server is connected **once per process** and kept open by a permanent pool
  consumer; each turn gets the individual tool objects. A per-tool switch is
  stored as the server's standard `tool_filters.rejected` and applied when the
  turn's tool list is built, so switching needs no reconnect. Every tool schema
  costs prompt tokens on every request; the manager estimates them.
- **Where tools come from.** Each MCP tool's description starts with
  `[MCP: <server>]`, and the prompt lists tools grouped by source (built in,
  skills, each MCP server). Without that, asked to use an MCP tool, the model
  used the built-in one with the same purpose.

## Memory

Off, enforced by validation. The harness memory store is a flat folder with no
chat or branch in its key, injected every turn, so a fact from one version of a
chat leaks into every other. Turning it on needs a design (scope per chat or
per branch), not a flag. `memory_manager.py` sets all four switches it takes to
keep it, and its tools, out of the request.

## Checking it

Atlas is tested by hand in the UI. The development tests and the benchmark
(`tests/`: offline rule tests, a live API test, `bench.py`) are kept on the
developer's machine and are not in the repository (`.gitignore`).
