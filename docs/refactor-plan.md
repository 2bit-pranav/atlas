# Refactor plan: toward a robust runtime

Written 2026-11-12 from an evaluation of `dev` at 37155ee: a read of the code, 31
hostile calls against the real `ToolPolicy` offline, the live suite's docs, safety
and recovery tasks (56/60), 19 runs of five harder document tasks (6 correct
files), four injection runs, and a prototype of the proposed pipeline (48/48 and
8/8 on the inputs the agent got wrong). The numbers and scripts are in
`benchmarks/2026-11-12-harder-documents/`; the reasoning, in plain words, is in
the Claude Doc "Atlas, explained".

## What stays

Not everything needs changing, and these were measured to be right:

- Strands and the harness, one agent per turn, hooks for recovery, immutable snapshots.
- The permission grid, the floor, taint, limits: the shape is correct; the holes are in what feeds it.
- The ingest store, reading by fetch, edits by address, atomic verified writes.
- One turn, no plan tool, no workers, no free-form memory (decisions.md, 2026-11-04 and 2026-10-17).

## Where it goes

Five changes of shape. Everything in the phases below is one of these.

1. **Two lanes on one run kernel.** Today every request is an open-ended agent
   loop. Add a workflow lane: code loops, the model answers one schema-constrained
   question per unit, code verifies and assembles. Both lanes share the run slot,
   cancel, limits, the trace and the event stream.
2. **Typed tools only; the shell is opt-in.** The classifier recognises safe
   commands, and a language cannot be enumerated. Skill scripts run through a
   typed `run_skill`; `shell` is off by default and always asks when on.
3. **Code owns "done".** A turn ends when a check says so, not when the model
   stops calling tools.
4. **One egress gate, one untrusted-content wrapper.** Every way bytes leave the
   machine goes through the same checks; every string the user did not type goes
   through the same fence. Taint follows where bytes came from, not which tool
   fetched them.
5. **A trace per run, written as it happens.** The exact request and response of
   every model call, every policy decision, every event. It is the debugger, the
   crash journal and the source of replayable test cases.

## Phase 0: close the leaks (first, small, each with a test)

Follow the repo's convention: add the test as `xfail(strict=True)` first, then
the fix removes the marker.

| # | Change | Where | Test |
|---|---|---|---|
| 0.1 | Render images in answers only from the workspace or `data:`; never a remote URL | `client/src/features/chat/Markdown.tsx` (`components.img`) | vitest: an answer with `![](https://x/y)` renders no `<img>` |
| 0.2 | Place every operand of a read-class shell command as write targets are placed; send each through `protected.refuses` and the grid; unplaceable = elsewhere | `agent/safety/grid.py::_shell`, `policy.py::_shell_targets`, `call_paths.py::_paths_of` | `cat ../../pairing-token`, `cat ../c2/x`, `cat ~/.ssh/id_rsa`, `grep -r t ../..` refused or asked (probe: `probe_policy.py`) |
| 0.3 | The skill-script exemption applies only to a command that is one simple command whose script resolves inside `skills/<skill>/scripts/` | `agent/safety/grid.py` (`_SKILL_SCRIPT`) | `python "$ATLAS_SKILLS/x.py"; python -c ...` and `$ATLAS_SKILLS/../..` ask |
| 0.4 | `read_url`: run `query_refusal` on the URL's path and query; cap its length | `agent/tools/web.py` | a URL carrying a path-like or long-number query is refused |
| 0.5 | A command grant covers that exact command text, not `run:<program>` | `agent/safety/policy.py::_grant` | allowing `python a.py` does not cover `python -c ...` |
| 0.6 | Uploaded files are read-only to the agent: change and delete of an upload ask | `agent/safety/grid.py::zone` (needs the turn's upload list on `Scope`) | `cat <<EOF > orders.csv` on an upload asks |
| 0.7 | Taint on bytes from outside whatever the route: panel uploads, `/files/import`, `page_show` results | `server/routes/files.py`, `agent/tools/page.py` | an imported web PDF taints the chat |
| 0.8 | Resolve message attachments by name inside the chat folder on the server; run `file://` import through `Scope` | `server/routes/turns.py`, `server/state.py`, `server/routes/files.py` | a message with `files[].path` outside the chat folder is rejected |
| 0.9 | Fill: one visibility test (on-screen rect, opacity, minimum size); Apply lists every field with its full value | `extension/lib/page/read.ts`, `extension/lib/fill/fill.ts` | vitest: an `opacity:0` field is not collected |
| 0.10 | Page title and URL capped, cleaned and moved inside the untrusted block; `</page>` neutralised | `agent/prompt/page.py`, `server/schemas.py` | a title with a newline and `</page>` cannot leave the block |
| 0.11 | The pairing token in its own storage key with trusted-context access only; private-address and redirect checks in `open_link` | `extension/lib/shared/settings.ts`, `skills/_shared.py` | content script cannot read the token; a redirect to 127.0.0.1 is refused |

Also: reset the pairing token once (it was printed into a probe chat during the
evaluation), and stop passing the full process environment to shell commands
(`windows_shell.py`: `ATLAS_LLAMA_KEY` is inherited by every command).

Exit: `probe_policy.py` shows no "RAN SILENTLY" row; the injection probe leaks nothing in 8 runs.

**Status, 2026-11-12:** every row above is done, each with a test, plus the
environment item; the probe shows no silent row. 0.6 exempts `edit_docx` and
`set_cell`; 0.10 cuts the title in the note instead of capping the schema; a
network command asks in every mode (not in the table). What each did is in
decisions.md under *Shell reads by relative path*. Still open: the injection
probe on the real model (it needs the GPU), and resetting the pairing token.

## Phase 1: see what happens

| # | Change | Where |
|---|---|---|
| 1.1 | `Trace`: JSONL at `.data/traces/<chat>/<run>.jsonl`, appended and flushed per event, deleted with the chat, capped by age | new `agent/common/trace.py` |
| 1.2 | Write `model_request` (the full body) and `model_response` (text, tool calls, finish reason, llama `timings` unmerged) per call | `agent/model/llamacpp.py` |
| 1.3 | Write `policy` per step that rewrote, asked or refused (step, effect, zone, verdict, the arguments that ran) | `agent/safety/policy.py::_before`, `limits.py` |
| 1.4 | Write every run event; store `run.id` in the turn's stats; a date on log lines | `server/runs.py::Run.emit`, `server/state.py`, `agent/cli/procs.py` |
| 1.5 | Per-call stats instead of last-call-wins: tokens in and out, cached against fresh prompt tokens, prompt ms, generation ms | `server/transcript.py` |
| 1.6 | `atlas trace [--last | <run>] [--prompt N]` prints the tree; `atlas replay <run> --call N` re-sends a saved request and diffs the output | `agent/cli/commands.py` |
| 1.7 | The UI's Details view links a turn to its trace; an interrupted turn shows what its trace recorded | `client/src/features/task/WorkPanel.tsx`, `server/views.py` |

Exit: for any turn, completed or not, `atlas trace` shows each model call's
exact prompt and the reason for every refusal.

**Status, 2026-11-12:** 1.1 to 1.7 done, with tests (a stand-in llama-server
for the adapter and for replay). The trace file is named by turn and run, so an
interrupted turn finds its own. Replay goes through a backend route, because the
llama key is never on disk. The UI part of 1.7 is a line under Details naming the
`atlas trace` command, not a trace viewer. Not checked on a real model run yet.

## Phase 2: documents that come out right

| # | Change | Where | Addresses |
|---|---|---|---|
| 2.1 | Strip reader markers before parsing: `[bN]`, the `[tN: table ...]` line, `rN:` rows back into a pipe table | `agent/tools/documents/markdown.py` | reader scaffolding in output (3 of 4 rewrite runs) |
| 2.2 | References in `create_document`: `{{file#t1}}`, `{{file!Sheet!A1:C41}}`, `{{sql: SELECT ...}}`, expanded from the ingest store or DuckDB, access-checked like image lines | `agent/tools/documents/create.py`, `call_paths.py` | retyped tables, wrong totals |
| 2.3 | SQL over CSV in the read tool (DuckDB reads CSV natively) | `agent/tools/doc_reading.py`, `reading.py` | data pasted into `python -c` |
| 2.4 | Done-check hook: the file the request named exists and opens; pages read against pages total for a summary; a last message that only states intent gets one resume | new hook beside `agent/recovery/tool_recovery.py` | announce-and-stop, fragment summaries, corrupt files |
| 2.5 | Validate every document a turn changed (`_check_docx`, `_check_xlsx`, `_check_pdf`); a file that does not open is an error shown to the user and the model | `server/services/workspace.py`, `server/state.py::_finish` | CSV saved as `.xlsx` |
| 2.6 | Register the writing tools at the start of a turn whose message or attachments name a document type; make the `write` refusal register them too | `agent/runtime/skill_tools.py`, `server/state.py` | two wasted calls on about half of writing runs |
| 2.7 | Port the five harder tasks into `tests/live/suite.py` (tag `hard`), with graders that open the file and check structure, not only strings | `tests/live/` | the suite's writing tasks pass 10/10 and hide all of the above |

Exit: `suite.py --tags hard --repeats 2` at 15/20 or better (today 6/19).

**Status, 2026-11-13:** 2.1 to 2.7 done, each with tests, none run on the model
yet. Found on the way: the workbook SQL could read any file on the disk through
DuckDB's own readers; it is sealed now (2.3). The done check (2.4) sends a turn
back once, and only for what code can see: a document that does not open, a file
the request asked to be made (a name after a word like "make" or "save as", not
after "of" or "from") that does not exist, a last line that only announces a step,
or a summary written without reading every page of a PDF of 40 pages or fewer. The five hard tasks' graders were checked offline against answers made
with the new references (all pass) and against the evaluation's failures (all fail).

## Phase 3: the workflow lane and the typed-tool runtime

| # | Change | Where |
|---|---|---|
| 3.1 | `ModelCall`: one schema-constrained request that takes the run slot (or a second llama.cpp slot), honours cancel, counts against limits, writes to the trace | new `agent/runtime/model_call.py` |
| 3.2 | Move Fill and Key moments onto it | `agent/extension/form_fill.py`, `moments.py` |
| 3.3 | `extract_table(files, columns)`: loop in code, one call per file, each value checked against that file's text, totals by `Decimal`, xlsx written, a short summary with what was flagged | new `agent/tools/pipelines.py` |
| 3.4 | `write_summary(file)`: walk the ingest outline, one sentence and one figure per section, figure checked in the section, document assembled | same |
| 3.5 | `compare_documents(a, b)`: code aligns blocks and diffs; the model describes each change | same |
| 3.6 | `run_skill(skill, script, args)`: argv list, no shell; inputs checked as reads, the output as a create | new `agent/tools/skills_run.py`; SKILL.md files reworded |
| 3.7 | `tools.builtin.shell` off by default; when on, every command asks with its full text | `agent/config/settings.py`, `grid.py` |
| 3.8 | Thinking chosen by code: off for chat and single reads, on for turns with several files or a document to produce; the UI switch becomes an override | `server/state.py` |
| 3.9 | A conversation manager that evicts old tool results to a one-line stub; a long-chat suite task before it is trusted; delete the unread settings | `agent/runtime/factory.py`, `agent/config/settings.py` |
| 3.10 | Contract tests for what Atlas assumes about Strands (reasoning arrives once, no `snapshot_latest`, the four memory switches, prompt reset after restore, non-zero exit) | `tests/test_harness_contract.py` |

Exit: the `hard` tasks at 18/20 or better with median time under 20 s; the
files and harm tags unchanged with `shell` off.

**Status, 2026-11-14:** 3.1 to 3.10 done, each with tests, none run on the model
yet.
- **Pipelines:** found on the way, a PDF's sections need no outline. Title lines
  in its text found all 8 sections of the review, including the first one, right
  after the document's title.
- **3.6:** script outputs now get a free name instead of replacing a file. That
  is what lets the policy treat an existing path argument as a read.
- **3.7:** the shell defaults to off, but a settings file with `"shell": true`
  keeps it on.
- **3.9:** "trim" replaced Strands' managers. Older settings files load as "trim".

## Phase 4: guardrails

| # | Change | Where |
|---|---|---|
| 4.1 | `Rail` protocol and `run_rails(stage, item, ctx)`; `ToolPolicy` is the action stage, unchanged | new `agent/safety/rails.py` |
| 4.2 | Egress stage in front of every outbound channel: `web_search`, `read_url`, `read_pdf` links, MCP arguments, `run_skill` with network scripts. Shape checks, an outbound-character budget once tainted, and overlap with the chat's ingested documents (FTS5 phrase query) | `agent/tools/web.py`, `agent/ingest/store.py` |
| 4.3 | Output stage: number provenance for created documents and final answers (every number appears in a tool result this turn or came from `calculate`), quote checking against the ingest store, "created X" only when a create succeeded | hooks in `agent/recovery/`, UI flag in `client/src/features/chat/` |
| 4.4 | Input stage: one `untrusted(text, source)` wrapper for every string the user did not type | `agent/prompt/page.py` generalised |
| 4.5 | Instruction detection at ingest: a phrase list first; a small ONNX classifier in the ingest worker only if the list proves too weak. A flagged document taints the chat when read and shows a notice | `agent/ingest/store.py`, `doc_reading.py` |

No model-judged guardrail on the hot path. Every rail's verdict goes to the trace.

Exit: a `rails` suite tag: 0 leaks over the injection and exfiltration tasks, 3
repeats; no added time to first token (rails are deterministic or run at ingest).

## Phase 5: speed and local features

Speed, in order of measured payoff (86% of model time is generation):

1. References (2.2) and pipelines (3.3 to 3.5) remove the largest generations.
2. Tools registered up front (2.6) and thinking chosen by code (3.8) cut calls and reasoning.
3. Two llama.cpp slots once pipelines exist (20% throughput, 0.22 GB, measured 2026-11-04).
4. Trim the fixed prompt (about 4,800 tokens): shorter docstrings, rarely used file tools on demand.
5. Save and restore the warmed prompt state per launch (about 3 s off a new chat's first word).

Features, first three: Table from a folder (3.3 with `find_files`), Fill a
template (placeholders in the user's own .docx, mapped by the Fill call), Ask my
folders (a background indexer and watcher over the allowed folders into the
ingest store). The rest are listed in the Claude Doc.

## Order and size

Phase 0 is days and should not wait for anything. Phase 1 before Phase 2: the
document fixes are much easier to tune with the exact prompt in hand. Phases 2
and 3 are the bulk. Phase 4's egress items 4.2 and 4.4 can move up beside Phase 0
if the extension is in daily use.

## Not doing

- Replacing Strands or writing a loop. The work is around the loop.
- A plan tool, worker agents, or any design where the model orchestrates.
- Free-form memory. A structured, user-edited table only, if at all.
- A second model as a judge on every answer.
- Sandboxing the shell with OS isolation: turning it off by default is cheaper and enough for this product.
