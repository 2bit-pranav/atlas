# Restructure and fix plan

How to reorganise Atlas so it can be read end to end and defended in an
interview, and the bugs and improvements to handle in the same cycle.

Status: plan, 2026-10-29, from a review of the 29 Oct snapshot (agent/core,
skills, server, agent/cli, client, extension). Findings marked **verified**
were checked against the source by hand; the rest come from the review and
should be confirmed (a failing test first) before they are fixed.

Updated 2026-10-30: safety tiers added (section 4). Section 2's layout, the
safety list in section 4, and section 5 were adjusted to match.

---

## 1. How to run the work

### The rule that matters most

**Never mix moving code and changing behaviour in one commit.**

- A *move* commit only relocates and renames: same behaviour, tests pass
  before and after.
- A *fix* commit changes behaviour, and adds the test that failed before it.

If a move and a fix share a commit and something breaks, nobody (you or
Claude Code) can tell which caused it. And the history becomes your
interview story: "here is the commit where I found and fixed the relative
path bypass, and here is its test."

### Phases

**Phase 0: a safety net (before anything moves).**

- Bring the tests into the repo. They are in an ignored `tests/` today, so
  a refactor has nothing to check against. At minimum, offline tests for:
  `policy.py` (access, install, taint), `maths.py`, the chat tree in
  `chats.py`, `RunManager` (approvals, client calls, cancel), and one
  end-to-end run against a fake llama-server (a small Python server that
  returns scripted tool calls; no model needed).
- Add checks: `ruff`, `pyright` (basic mode), `pytest`; for TypeScript,
  `tsc --noEmit` and `oxlint`. A GitHub Actions workflow that runs all of
  them on every push.
- Tag the current commit (`pre-restructure`) and record the benchmark score.
  The safety tiers (section 4) must later reproduce this score: run the
  benchmark in the Work tier with an approver that answers "allowed".

**Phase 1: the critical fixes, small and with tests.**
The high-severity items in section 3 (B1-B8). They are local edits, they are
live risks, and their tests become part of the safety net for Phase 2.

**Phase 2: the restructure, moves only.**
In this order, one area per Claude Code session:

1. `agent/` safety core: policy, approvals, recovery, shell environment.
   This is what interviews probe first.
2. The rest of `agent/`: model, prompt, tools, store, integrations.
3. `server/`.
4. `agent/cli/`.
5. `client/` (also check the extension still builds, since it uses
   `client/src` as its source folder).
6. `extension/`.

**Phase 3: the remaining bugs and improvements**, each as its own commit with
a test. Safety first, and the safety tiers (section 4) before any new
feature: they change what gets asked, so they need the Phase 0 tests and the
B1/B2 fixes underneath them. Phase 2 only moves code; the tier files marked
NEW in section 2 are created in Phase 3.

### Working with Claude Code

- Start each session by pointing it at `CLAUDE.md`, the folder's `AGENTS.md`,
  this file, and the section of the layout it is working on.
- Ask for a plan first, approve it, then let it execute. Ask it to run the
  tests after every step and stop on the first failure.
- Ask it to keep the folder `AGENTS.md` (or a short `README.md`) current as
  files move: one line per file, saying what it owns.
- Comments: a docstring says the rule and, in one line, why. History ("600
  was too few", "found by test") moves to `docs/decisions.md`.
- TypeScript: turn on `"strict": true` and fix what it finds (as fix
  commits, not inside moves).

### Making it yours

After each area is restructured, before starting the next:

- Read the area yourself in the reading order below, without the AI.
- Write five lines in your own words on what it does, in that folder's
  README. Anything you cannot write is something to ask about.
- Break one thing on purpose and watch which test catches it.

---

## 2. Target layout

### agent/

```
agent/
  config/        settings.py, paths.py
  model/         llamacpp.py   (AtlasLlamaCppModel; split _stream_body into an SSE parser
                                and the reasoning splitter)
                 server.py     (llama.py: api key, health)
                 sampling.py   (build_model, build_summarizer)
  prompt/        system.py     (_runtime_facts, _tool_sources, _compose_instructions)
                 notes.py      (clock_note, retry_hint, page_note)
  runtime/       factory.py    (build_agent only, ~40 lines)
                 restore.py    (_restore, _harness_prompt, the sync/async bridge)
  safety/        policy.py     (ToolPolicy: runs the steps in order; Decision type)
                 scope.py      (the allowed roots; ONE resolve_for_access() used by every step)
                 call_paths.py (which paths a call touches: file tools, shell, MCP)
                 steps/        normalise.py, floor.py (NEW), access.py, install.py,
                               taint.py, sensitive.py, binary_guard.py
                 tiers.py      (NEW, Phase 3: Look / Ask / Work; resolve(effect) -> allow | ask | refuse)
                 shell_classify.py (NEW: parse a command -> read-only | workspace write | other)
                 rules.toml    (NEW: the floor, read-only verbs, known skill scripts, with examples)
                 installs.py   (install detection)
                 approvals.py  (Approver; decisions as an Enum)
  recovery/      model_retry.py (LocalModelRetry), tool_recovery.py (ToolFailureRecovery)
  platform/      windows_shell.py (WindowsLocalEnvironment, process kill)
                 winpaths.py      (drive_path, windows_path, model_path, cygpath)
  tools/         documents/   markdown.py, docx.py, pdf.py, xlsx.py, edit.py, atomic.py, tool.py
                 maths/       evaluator.py, dates.py, tool.py
                 page.py      (page tools for the extension)
  store/         chats.py, snapshots.py (session_manager)
  integrations/  mcp/    pool.py, config.py, registry.py
                 skills/ catalog.py, installer.py, requirements.py, readers.py
  extension/     form_fill.py, table_export.py (write_table, from page_tools)
  common/        spreadsheet.py (one cell-coercion rule, sheet names, autofit), results.py (ok/error)
  cli/           see below
```

What this fixes: `agent_factory.py` does agent assembly, prompt text, scope,
path display and snapshot restore; `shell_env.py` mixes processes with path
translation; `documents.py` is a parser, three writers and an editor in 751
lines; `skill_manager` and `skill_installer` import each other.

### server/

```
server/
  app.py            create_app: middleware, lifespan, include_router (short)
  state.py          Atlas (store, runs, mcp, settings) as a FastAPI dependency
  schemas.py        request models (app.py 79-155)
  views.py          _turn_view, _run_view
  routes/           chats.py, files.py, turns.py, runs.py, settings.py,
                    extension.py (with a web_ui_only dependency), skills.py, mcp.py, spa.py
  services/         run_service.py (launch, execute, _finish)
                    prompt.py      (_agent_text, _mention_guidance, _link_guidance, media)
                    workspace.py   (_scan, _changed, workspace_file, safe upload names)
                    settings_service.py
  runs.py, events.py, transcript.py, security.py   (keep)
```

`create_app` is about 455 lines of nested closures today.

### agent/cli/

```
agent/cli/
  main.py         argument parsing only
  commands.py     cmd_start, cmd_stop, cmd_status, cmd_logs
  launcher/       services.py (start llama, backend, web), supervisor.py (supervise,
                  restart protocol), logs.py (rotation)
  procs.py        processes.py + the port/PID parts of launched.py
  launched.py     the record file only
  views/          plain.py, dev.py, screen.py, keys.py
```

### client/src/

```
client/src/
  main.tsx, App.tsx          (routes only)
  app/        Shell.tsx, useGlobalShortcuts.ts, DeleteChatDialog.tsx
  api/        client.ts (request, auth), chats.ts, runs.ts, settings.ts, skills.ts,
              mcp.ts, extension.ts, sse.ts (streamRun), types.ts
  state/      store.ts (store + useAtlas only), chatSlice.ts,
              runStream.ts (attach/follow/flush/finish: the replay logic),
              uploads.ts, restart.ts, host.ts (typed setHost for the extension)
  features/
    chat/       ChatScreen, TurnRow, UserMessage, AssistantMessage, ApprovalCard,
                Reasoning, StatsBar, VersionSwitcher, ProducedFiles, Attachments,
                Markdown, ToolBlock, transcript.ts
    composer/   Composer, InlineEditor, MentionMenu, useMentions.ts, useRecorder.ts, audio.ts
    settings/   SettingsPage, FieldRow, sections/*.tsx, schema.ts
    skills/, mcp/, extension-page/
  hooks/      useNow, usePrefs, useChatRoute, useAsyncAction
  components/ui/   one component per file
  lib/        format.ts (formatBytes, fileExt, timeAgo), download.ts, cn.ts
```

Conventions for a reader new to React: one component per file with its
`Props` type above it; no index re-export files; `strict` on; every async
action returns a result instead of each caller needing try/catch.

`store.ts` does nine jobs in one class (startup, settings, restart, chats,
uploads, turns, streaming, export, extension hooks). The streaming part
(`seq`, replay, `generation`, one update per animation frame) is the most
interview-worthy piece of the client, so it gets its own file.

### extension/

```
extension/src/
  shared/   messages.ts (typed ops and results), url.ts, backend.ts (uses the client's api)
  page/     read.ts, tables.ts, images.ts, text-index.ts, highlight.ts,
            dispatch.ts (one run(op, args), used by content.ts AND the PDF viewer)
  fill/     collect.ts, preview.ts, apply.ts
  ui/       overlay.ts, chip.ts
  panel/    Panel.tsx (~120 lines: which view)
            hooks/      useConnection, useActiveTab, usePageBinding, usePendingAsks, useLastChat
            components/ PageHeader, TabBanners, QuoteSources, HistoryView, SettingsView, FillStatus
            actions/    pageCall.ts, suggestFill.ts, pdf.ts
```

Share with the client instead of duplicating: a `ChatList` component (the
panel's HistoryView repeats the sidebar's), `api.health()` and `api.saveTable`
(hand-written in `Panel.tsx` and `background.ts`), one PDF fetch helper.

---

## 3. Bugs

### High: Phase 1

| # | Where | Problem | Status |
|---|---|---|---|
| B1 | `agent/core/policy.py:332-335` | Relative paths are never access-checked (`if raw.startswith("/") or ...is_absolute()`). `create_document("../../settings.json.md")` or `edit_document("../../../mcp.json")` writes outside the workspace without asking. | verified |
| B2 | `agent/core/policy.py:338` | `raw.rstrip(".,)")` turns `rm -rf /c/Users/me/allowed/..` into `.../allowed/`, which passes. | verified |
| B3 | `server/app.py:274-299` | Prompt assembly runs before the `try` in `execute`. Any exception there (e.g. a file entry without `name`, `_scan` racing a deletion) never frees the run slot: every send returns 409 until restart. Move it inside the `try`. | verified (placement) |
| B4 | `client/src/lib/store.ts:263` | A window with no page handler answers the extension's page calls with an error. A web UI tab on the same chat answers first, so `page_read` fails. Only a client with a handler should answer. | verified |
| B5 | `server/runs.py:57`, `policy.py:199-229` | Page taint lasts one run, but page text stays in history: on the next turn, injected instructions are ungated. Taint also never covers MCP tools, `web_fetch`, or the saved `page-*.md`. | verified (per-run flag) |
| B6 | `server/app.py:397` | Port 5173 is trusted even when the UI is served by the backend. Any page on `localhost:5173` (Vite's default for every project) gets the full API, including `POST /api/mcp` with an arbitrary command. Trust it only in `--dev`. | verified |
| B7 | `agent/cli/processes.py:232-240`, Job flags at 106-107 | Windows: `terminate()` kills the child, so the later tree kill returns early; with `SILENT_BREAKAWAY_OK`, grandchildren (MCP servers, Vite's node) are not in the job. Every stop or restart leaks MCP servers. | verified (logic) |
| B8 | `agent/core/maths.py:135` | The thousands-separator rule merges arguments: `max(10,20)` becomes `max(1020)`. | verified |

### Medium

| # | Where | Problem |
|---|---|---|
| B9 | `policy.py:196` | Approving one file grants its whole parent folder, for writes too, for the rest of the turn. A read of `C:/x` grants `C:/`. |
| B10 | `approvals.py:20` | Install detection misses leading spaces, newlines, `py -3 -m pip`, a full path to `python.exe`, `pipx`, backticks, `X=1 pip install`. Parsing the command beats extending the regex. |
| B11 | `app.py:326-334` | Cancel while text is streaming can end the loop normally, so the turn is saved COMPLETED with a snapshot. Re-check `run.cancel` after the loop. (Plausible: depends on Strands' cancel events.) |
| B12 | `app.py:662-677` | Edit checks the run slot, awaits snapshot deletion, inserts a RUNNING turn, then launches. A send in between leaves a turn stuck RUNNING. Take the slot before the await. |
| B13 | `app.py:531-539` | Uploads overwrite a same-named file silently (retries then read the wrong file); `""`, `.`, `..` give a 500; no size limit (`/skills/upload` reads the whole zip into memory). |
| B14 | `agent/cli/main.py:122`, `launched.py:33` | `atlas stop` sweeps all ports and matches `node`/`llama` by name, killing the user's own dev server or llama-server. |
| B15 | `agent/cli/views.py:68`, `screen.py:267` | Ctrl+C during start-up skips `launcher.stop()`; children in their own session keep running. |
| B16 | `maths.py:120-125, 139, 162` | Decimal errors (`sqrt(-1)`, divide by zero, overflow) escape as crashes and get retried; the `%` rewrite makes `10 % 3` a syntax error. |
| B17 | `documents.py:641-654` | docx `replace_all` replaces only the first run but reports every match; hyperlink text is duplicated; an all-hyperlink paragraph raises. |
| B18 | `documents.py:660, 450-461` | Editing an xlsx with openpyxl drops charts and images; `"00123"` becomes `123` (IDs, PIN codes). |
| B19 | `documents.py:514`, `page_tools.py:200`, `combine_xlsx.py` | Cells starting with `=` become formulas, including cells copied from web pages: formula injection into the user's spreadsheet. |
| B20 | `agent_factory.py:91,112` | `context.window` (default 32768, never falsy) shadows `model.context_size`, which is what llama-server actually got. |
| B21 | `skill_manager.py:89` | Every message rediscovers skills, which can run `npm ls -g` (30 s timeout). Cache it. |
| B22 | `skills/pdf/scripts/read_pdf.py:146-151` | `--search` OCRs every page of a scan; a long scan hits the 120 s shell timeout, and the error hint recommends `--search`. |
| B23 | `store.ts:209-216`, `App.tsx:190` | A failed `openChat` leaves the app busy (Stop stays, Send disabled); fast chat switching can show chat A under chat B's URL. |
| B24 | `Composer.tsx:83-106`, `audio.ts:46` | Recording has no cleanup on unmount: the microphone stays on after leaving the screen. A new AudioContext per recording is never closed. |
| B25 | `Messages.tsx:253`, `server/app.py:608` | An uploaded SVG opened from its chip may run script on the app's origin. Serve uploads with `Content-Security-Policy: sandbox` or as attachments. (Confirm: the review found agent-written files are served safely; check uploads use the same path.) |
| B26 | `extension/entrypoints/viewer/main.ts:97` | A read while a PDF is loading says "page 3 of 3" for a 200-page file. |
| B27 | `extension/lib/page.ts:262-271` | Links and inline elements split text blocks, so quotes spanning a link are reported "not in the page". |
| B28 | `extension/lib/settings.ts:39`, `background.ts:51` | Pairing accepts any localhost port: a page on another local port can point the extension at its own server. Pin the backend port. |
| B29 | `extension/lib/page.ts:106-108` | The element list sends typed values of non-password fields (OTPs, card numbers) to the model and transcript. |
| B30 | `skill_installer.py:42, 125-137, 172` | A GitHub path with `..` escapes the temp folder; zip/tar have no size cap. |
| B31 | `mcp_manager.py` `describe()` | Returns full server config, including `env` API keys and headers, to the UI and extension. Redact. |
| B32 | (missing) | Nothing protects `settings.json`, `mcp.json`, `.data/`, the venv or `skills/` from the agent. With B1, `../../..` reaches them from any workspace. |

### Found during Phases 0-1 (2026-10-30)

| # | Where | Problem |
|---|---|---|
| B33 | snapshot storage, `paths.data_dir` | With Windows long paths off (the default after a clean install), a data folder deeper than ~75 characters puts snapshot paths past 260 characters, and **every turn fails** at the save (`StorageError: Failed to write ...`) after doing its work. The user's `.data` is fine (184); a data folder under `%LOCALAPPDATA%` (the planned move) would not be. Check at start-up and say so, or shorten the snapshot layout. |
| B34 | `maths.py` `_tidy` | The `%` rewrite takes one digit: `2750 * 18%` becomes `2750 * 1(8/100)` and fails; `18% of 2750` works by accident. Part of B16; test is `xfail` in `tests/test_maths.py`. |
| B35 | `client/package.json` | `npm audit`: KaTeX (low, renders model output, which can carry web text), postcss-selector-parser (moderate, build only). Update KaTeX and check its `trust` settings. |
| B36 | UI | Sending after a failed turn returns 409 by design (retry or edit instead), but the user is not told why the message did not send. |

Fixed during Phase 0, not in the table above: the lock file lacked
`strands-harness` and `reportlab` (a fresh venv could not start the backend),
and the benchmark counted failed turns as passes.

### Low

- Replayed `client_call` events run again when the panel reopens mid-run (`store.ts:445`).
- An approval card cannot be answered again after a failed POST (`Messages.tsx:157`).
- Global shortcuts fire inside text fields (`App.tsx:66-69`).
- The inline editor moves the caret to the end on every re-render (`Composer.tsx:125-131`).
- Errors swallowed silently: export, skill/MCP toggles in Settings, import.
- Cleared number fields save `0` (`SettingsPage.tsx`).
- The log filter can get stuck labelling every line as a traceback after `httpx.ReadTimeout` (`log_filters.py:92`); llama crash lines without a timestamp are dropped (`:146`).
- `hmac.compare_digest` raises on a non-ASCII token: 500 instead of 401 (`security.py:54`).
- Text edits are not atomic (`documents.py:599`).
- The content script can be injected twice (`tab.ts:52`).
- The fill secret filter skips "Passport no." and "PIN code" (`fill.ts:21`); the fill count includes values the field rejected (`:139`).
- Shutdown closes the database while runs are finishing (`app.py:388-391`).
- A synchronous `httpx.get` runs on the event loop in `settings_view` (`app.py:190`).
- `query_xlsx` names an empty header `"None"`; the SQL deny-list rejects `WHERE status='Delete'`.
- Snapshot ids from an imported chat are used in file names (`session_manager.py:93`): check Strands sanitises them.
- The prompt says "you may install with python -m pip" while skills say "do NOT run pip install".

### Dead code and duplication (one cleanup commit per area)

- Python: `SkillManager.harness_skills`, `set_thinking`/`thinking_enabled`, `MemoryManager.verify_off`, `SessionManager.policy`, `maths.NAMES`, `ToolManager.extra_tools`, unused `context.prune_target_ratio`/`generation_reserve`, the `data/chats` fallback in `_shared.resolve`, the unused `args` dict in `events.py`, `transcript.answer_text`, the unused `"run"` launcher event.
- Three different cell-coercion rules (documents, page_tools, combine_xlsx): make one.
- Four copies of the extension-origin check in `app.py`; five `SessionManager(...)` constructions.
- Client: unused `api.saveTable`; unused packages (`class-variance-authority`, two Radix packages); file-badge logic copied three times; the `run()` error wrapper copied in Skills and MCP pages.
- Extension: the op switch in the PDF viewer duplicates `content.ts`; the health check and PDF fetch are written twice.

---

## 4. Improvements

### Safety (Phase 3, first)

1. One `resolve_for_access()` for every path (fixes B1, B2 and the duplicated
   "absolute or locate" logic in five places).
2. Protected paths (B32): `settings.json` and `mcp.json` are on the floor
   (an agent that can edit them can raise its own tier or add an MCP server).
   `.data/`, the venv and `skills/` are never auto-allowed, in any tier.
3. Taint per chat, not per run, and covering MCP tools and `web_fetch` (B5).
   Show it in the UI ("this chat has read a web page"). A tainted chat behaves
   as the Ask tier whatever its tier is (see Safety tiers).
4. Parse shell commands instead of matching paths and installs with regexes
   (tree-sitter-bash or `bashlex`): `shell_classify.py` places each command as
   read-only, workspace write or other, and the tier decides what each class
   does (see Safety tiers).
5. Policy rules as a data file (`rules.toml`), with a hard floor (`rm -rf`,
   `format`, `del /s`) that no setting or tier can lower. The file carries
   example commands that are checked when it loads.
6. Cheap caps for every run: maximum model calls, wall-clock limit, and a
   three-identical-calls check. Needed before scheduled runs exist. A run with
   nobody to ask (scheduled, watched folder) refuses everything that would ask.
7. Extension token scoped to chat, run and extension routes; drop `?token=`;
   pin the pairing port (B28); trust 5173 only in dev (B6).
8. Redact secrets in MCP `describe()` and install-command logs (B31).

### Safety tiers (Phase 3, after items 1, 4 and 5)

Three trust levels, chosen per chat. They answer one question for each call
the policy steps flag: **allow, ask, or refuse?** They do not replace a step,
the access scope or the approval card. They only decide what an "ask" becomes.

| Call | Look | Ask (default) | Work |
|---|---|---|---|
| Read-only, inside scope (`ls`, `stat`, `head`, reader scripts, `calculate`, web search) | allow | allow | allow |
| Write in the chat's own workspace (documents, bundled-script output) | refuse | allow | allow |
| Write in `access.folders` (`edit_document`, `write`, `cp`, `mv`, `>`) | refuse | **ask** | allow |
| Delete (`rm`, `del`), or a shell command the classifier cannot place (`python -c`, `git push`, `curl`) | refuse | ask | ask |
| Install | refuse | ask | ask |
| Read outside scope (the existing access card) | ask | ask | ask |
| Write outside scope | refuse | ask | ask |
| MCP tool marked "ask" in Settings | refuse | ask | ask |
| The floor (`rules.toml`) | refuse | refuse | refuse |

Look means nothing on this computer changes: it still reads, searches the web
and asks about files outside scope. A Look refusal tells the model so ("this
chat is in Look mode, nothing can be changed; tell the user they can switch to
Ask"), in the same style as the current refusals, so it does not try another
way.

**What does not change**

- The approval card (Allow / Deny, 60 s, timeout means deny) and the access
  scope (workspace plus `access.folders`). `access.ask_outside` off still
  refuses outside scope, in every tier.
- First refusal wins. The order becomes normalise, **floor**, access, install,
  taint, sensitive, documents. The floor goes right after normalise so it sees
  the same paths and commands as the other steps. No step calls the approver
  directly any more: each asks `tiers.resolve(effect, detail)`, which returns
  allow, ask or refuse. That is one place to read, and one place to test.
- Taint. The page step stays as it is: after a page is read, shell commands
  and writes outside the workspace ask. In the Work tier that means writes
  into `access.folders` ask too, so a tainted chat is the Ask tier in effect.
  Taint is per chat (B5). A later relaxation (read-only commands skip the page
  ask once the classifier has proven itself) is possible but not part of this:
  the extension's approval screen currently promises that commands ask.
- Nobody to ask (a scheduled run, a watched folder). `approver=None` already
  refuses; keep that and test it. A scheduled run uses Work plus the caps in
  item 6, and anything that would have asked is refused and listed in the
  run's receipt, to approve later.
- The extension's Read / Suggest / Act ladder (`docs/extension.md`) governs
  what happens to the page and stays "the user confirms in the page" in every
  tier. Tiers govern Atlas's own tool calls.

**What changes for users.** Today the workspace and `access.folders` are read
and written silently, `shell` runs silently apart from installs and tainted
chats, and `_paths_of` marks every shell path as a read (`policy.py:338`). So
Ask is stricter than today in two ways: writes into `access.folders` ask, and
shell commands that are neither read-only nor a known script ask. Work is
today's behaviour, except that unclassified shell commands still ask.
Consequences to handle in the same change:

- Benchmark: run it in Work with an approver that answers "allowed", through
  the same code path, so the score stays comparable to the 5/12 baseline.
- `docs/demo.md`: Demo 1 writes into `Demo/Reports`. Set the chat to Work
  (add it to "Before going on"); Demo 3's outside-scope Deny moment is the
  same in every tier.
- The approval card gets a second button, "Allow edits to this folder for
  this chat". It grants write on that exact folder, not its parent, so it also
  fixes B9. Without it the Ask tier turns into click fatigue.

**Where the tier lives.** A setting `access.trust` (`look`, `ask`, `work`;
default `ask`) and a per-chat override stored on the chat record. Do not call
the type `Tier`: `settings.py` already uses that name for live-versus-restart.
The tier is read once, when the turn's agent is built, and passed to
`ToolPolicy`; nothing the model can call changes it. That is why `settings.json`
and `mcp.json` are on the floor (item 2).

**The classifier.** "Read-only" means "changes nothing", not "may read
anywhere": the access step still decides where. A command is read-only only if
it parses to verbs on the list with no redirect, `$(...)`, backticks, `eval`,
`xargs`, `find -exec/-delete`, `sed -i`, or a pipe into anything off the list.
Bundled skill scripts are known by path with an effect. Readers are read;
merge, split and convert are workspace writes, and an explicit output path in
`access.folders` is a write there and asks. Without this table the Ask tier
would prompt on every PDF read.

```toml
# agent/safety/rules.toml: read once at start-up. A rule whose examples
# disagree with it stops the start-up, so the file is also its own test.
[floor]
shell = ["rm -rf /", "curl * | sh", "format *", "del /s *"]
paths = ["{settings_json}", "{mcp_json}"]

[[read_only]]
verbs      = ["ls", "dir", "stat", "wc", "head", "tail", "cat", "file", "du", "tree", "rg", "grep", "find"]
deny_flags = { find = ["-exec", "-delete", "-ok"] }
match      = ["ls -la work", "find . -name '*.pdf' | wc -l"]
not_match  = ["find . -delete", "ls > out.txt", "cat a | tee b"]

[[script]]
path = "skills/pdf/scripts/read_pdf.py"
effect = "read"           # also: "workspace_write"
```

**Tests** (table-driven from the examples above, in `tests/safety/test_tiers.py`):

- Every row of the table, for each tier.
- Invariants: no floor example is allowed in any tier; Look never changes a
  file (run the write examples under Look and compare the folder before and
  after); taint never raises what a call may do; `approver=None` never allows;
  `ask_outside=False` refuses outside scope in every tier; the tier cannot
  change during a run.

**Order of work.** (1) Items 1, 4 and 5 and B1/B2, which this stands on.
(2) `rules.toml`, its loader and the floor step. (3) `tiers.resolve` and the
swap from direct approver calls, with `access.trust` and the per-chat
override. (4) Server field and route, the composer chip, the second card
button. (5) `demo.md`, the folder `AGENTS.md` files, `docs/decisions.md`.

### Product (after the restructure, from earlier discussions)

- A quick-actions skill (`files` list/find/stat: the read-only class of the
  safety tiers, so allowed in every tier)
  and `organize(plan)` with plan, approve, apply, undo.
- An activity view: what a run read, wrote and checked, with undo.
- Task cards on the empty state instead of a blank chat box.
- The document library, then facts memory.
- Watched folders and schedules, with the caps above.

### Engineering

- Tests and CI (Phase 0).
- `strict: true` in TypeScript; `pyright` on the Python side.
- Update `server/AGENTS.md`: three routes are missing (`/extension/pdf`,
  `POST /chats/{id}/files/import`, `DELETE /chats/{id}/files/{name}`), and
  `client/AGENTS.md` says picking a file in the @ menu attaches it, which it
  no longer does.
- `docs/architecture.md`: one turn, end to end, with links to the files.

---

## 5. What you should be able to explain afterwards

A checklist for interviews, with where each piece lives after the
restructure:

| Topic | Where |
|---|---|
| What a turn is: build the agent, restore a snapshot, stream, save | `agent/runtime/`, `server/services/run_service.py` |
| The tool policy: steps in order, first refusal wins | `agent/safety/policy.py`, `steps/` |
| Safety tiers: what Look, Ask and Work allow, ask and refuse; the floor beneath them | `agent/safety/tiers.py`, `rules.toml`, `steps/floor.py` |
| How a shell command is classified, and why read-only is not "may read anywhere" | `agent/safety/shell_classify.py` |
| How the access scope is decided, and its limits (not a sandbox) | `agent/safety/scope.py`, `call_paths.py` |
| Approvals: an event out, a future waiting, a timeout that means deny | `server/runs.py`, `agent/safety/approvals.py` |
| Taint and prompt injection from web pages | `agent/safety/steps/taint.py`, extension `page/read.ts` |
| Recovery: why hooks and not prompt text | `agent/recovery/` |
| The chat tree: retry vs edit, immutable snapshots | `agent/store/chats.py`, `snapshots.py` |
| Streaming: sequence numbers, replay on reconnect, one update per frame | `server/runs.py`, `client/src/state/runStream.ts` |
| Local security: Host check (DNS rebinding), Origin check, pairing token | `server/security.py` |
| The llama.cpp adapter fixes | `agent/model/llamacpp.py` |
| Windows process supervision | `agent/cli/procs.py`, `agent/platform/` |
| Extension message flow: panel, content script, backend | `extension/src/panel/actions/pageCall.ts`, `page/dispatch.ts` |
