# Atlas on Strands: Architecture and Tool Ecosystem

Status: design agreed through 2026-10-07. Scope: backend chat pipeline, run engine, tool ecosystem, context management. Frontend rebuild comes later.
Open topics still to design: RAG-like retrieval across documents (section 17), factual memory (section 17).
Next milestone: Strands/DuckDB spike (section 16), then schema + executor + core tools.

Changes since the 2026-10-06 version (so nothing is silently different):
- New: tool ecosystem (section 11), skills as the single extension mechanism, DuckDB data store, notepad, document skill, result offloading.
- Revised: the context rule "never prune the current turn" is replaced by "nothing is deleted, old results are demoted to stubs" (section 10).
- Revised: attachments are ingested at attach time into the data store (section 12), not just text-extracted.
- Revised: `recall` is merged into `show`; `search_results` is merged into `search` (fewer tools).
- Revised: `steps` for tool results store a preview + object id; full bodies live in the data store.
- Added events: `skill_loaded`, `object_created`, `scratch_updated`, `doc_rendered`.

---

## 1. Goals and non-goals

**Goals**
- A solid chat pipeline: prompt + attachments + a few toggles in, streamed agent output out.
- Edit-prompt and retry, with every version kept and browsable via `<` `>`.
- Every turn runs as an isolated **run** that keeps going if the frontend disconnects or dies.
- Force-stop (cancel) of a running inference without restarting any server.
- **Reliable everyday document and data tasks on a small local model** (Gemma-class, 32k window, ~70-90 tok/s). Reliability comes from the harness, not from asking the model to recall library syntax.
- A foundation that accepts new capabilities (pptx, pdf forms, ...) by adding skills, plus sub-agents, verification gating and automations later, without schema changes.

**Non-goals (for now)**
- Runtime model swapping, token-budget thinking control, run queueing, mid-run checkpoint/resume, multi-user.

---

## 2. Decisions log

| Topic | Decision |
|---|---|
| Launch | One CLI starts client, FastAPI and llama-server from `settings.json`. Force-quitting the CLI kills all. |
| Model | One model, fixed at launch. No swapping. |
| Thinking | Boolean `thinking`, not token budgets. Hidden if the model has no thinking support. |
| Settings | `settings.json` is the single source of truth. Per-message input exposes only toggles (currently `thinking`). |
| Setting tiers | **Restart-needed**: model, context size, GPU layers, ports. **Live**: top_p, top_k, temperature, system prompt, thinking default. Live settings apply from the next run. |
| App state | SQLite (WAL, foreign keys on). |
| Data store | **DuckDB**, one file per chat, for tables and analysis. SQLite remains for app state. |
| Concurrency | One active run globally. No queue. 409 on a second start. Send button disabled while a run is active. |
| Branching | Message tree. Edit = sibling user node. Retry = sibling assistant node (new run). |
| Retry | Restarts from step 0. No checkpoints. Interrupted/failed/cancelled runs are recovered by retrying. |
| Cancel | Required in v1. |
| Extension mechanism | **Skills.** A skill = instructions + tools + scripts. Loading a skill activates its tools. Document capabilities (docx now, pptx later) are skills. The model does not know whether a capability is built-in. |
| Always-on tools | Only universal basics: file/data access, notepad, `load_skill`. |
| Charts | Rendered as images (PNG) in v1. |
| Data passing | **By reference.** The model never retypes bulk data; tools take result ids or SQL. |
| Context window | 32k. Budget split in section 10. |
| Attachments | All document types in v1. |

---

## 3. Process model and CLI

Three child processes supervised by the CLI:

1. **llama-server**: spawned with restart-tier settings; the CLI waits for `/health`.
2. **FastAPI backend**: owns SQLite, DuckDB files, the run executor, event streaming.
3. **Client dev/static server**.

CLI responsibilities:
- Read and validate `settings.json`, spawn, prefix and stream logs.
- Write `launched.json` (restart-tier values actually used + a `launch_id`). The backend compares it to `settings.json` to show "restart required".
- On exit/force-quit, kill the whole process group (Windows: job object). Test early that no orphaned llama-server keeps VRAM.

Per-chat workspace on disk: `workspace/<chat_id>/{data.duckdb, uploads/, scratch/, outputs/}`.

---

## 4. Settings

| Key | Tier |
|---|---|
| model path/name, context size, GPU layers, ports, `supports_thinking`, `supports_vision` | restart |
| top_p, top_k, temperature, system prompt, default `thinking`, pruning thresholds, per-result token cap, display budget, max tool iterations | live |

- A run **snapshots** resolved live settings (`runs.settings_snapshot`) and records the `launch_id`.
- Per-message options are validated against an allowlist (`thinking` only). Unknown keys return 422.
- UI edits to restart-tier keys write the file and show "restart required".

---

## 5. Data model (SQLite, app state)

Conventions: ULID primary keys, integer epoch-ms timestamps, JSON as TEXT.

### chats
`id`, `title`, `root_id` (FK nodes), `created_at`, `updated_at`, `deleted_at`.

### nodes (the tree)
| Column | Notes |
|---|---|
| id | PK |
| chat_id | FK |
| parent_id | FK nodes; null only for root |
| role | `root`, `user`, `assistant` |
| content | user: JSON blocks (text, attachment refs). assistant: null (content in `steps`) |
| run_id | assistant only; FK runs; unique |
| selected_child_id | which child the UI shows |
| task_state | assistant only: JSON {plan, notes, active_skills} compacted at run end |
| created_at | sibling order |

- Synthetic `root` node per chat, so editing the first message is an ordinary sibling operation.
- Visible path = root, then `selected_child_id` to the leaf. Switching versions = update one `selected_child_id`.
- New user messages attach only to root or to an assistant node whose run is `completed`.
- Assistant node is created at run start. System prompt is not in the tree (comes from the snapshot).

### steps
`id`, `node_id`, `idx`, `kind` (`thinking` | `text` | `tool_call` | `tool_result`), `content` (JSON), `call_id`, `is_error`, `status` (`complete` | `partial`), `tokens`, `object_id` (for tool results that were offloaded).
For offloaded results, `content` holds the preview shown to the model and `object_id` points at the full body. The context builder reads only `steps`, skips `thinking`.

### runs
`id`, `chat_id`, `user_node_id`, `assistant_node_id`, `origin` (`send`/`retry`/`edit`), `status` (`running`/`cancelling`/`completed`/`failed`/`cancelled`/`interrupted`), `options`, `settings_snapshot`, `launch_id`, `error`, `usage`, `context_stats`, `last_seq`, `started_at`, `finished_at`.
**Global lock:** a partial unique index over a constant expression for rows with status `running` or `cancelling`; a second concurrent start fails the constraint and becomes 409.

### run_events
PK (`run_id`, `seq`); `ts`, `type`, `payload`. Append-only replay log.

### Attachments
- `attachments`: id, sha256, original_name, mime, size, storage_path, handle, created_at (deduped by hash).
- `node_attachments`: node_id, attachment_id, position. Copied to the new user node on edit unless removed.
- `attachment_extractions`: attachment_id, extractor_version, status, mode, outline (JSON), table_ids, warnings (JSON), token_count, page_count, error. Unique on (attachment_id, extractor_version).

### Catalog and objects
- `catalog_objects`: id, chat_id, run_id, step_id, node_id, name, kind (`table` | `text` | `file` | `doc_draft`), store (`duckdb` | `sqlite` | `disk`), schema (JSON), row_count, tokens, provenance (the SQL/tool call that produced it), created_at.
- `text_objects`: object_id, body, plus an **FTS5** index over it (text tool results, extracted document chunks with their locations).
- Objects are **immutable**: nothing is edited in place; a derived object is created instead. Every number therefore has recorded lineage.
- **Branch visibility:** tools resolve an object id only if it is an attachment of the current chat or was created by a node on the current path.

### scratch_state
`run_id`, `plan` (JSON), `notes` (JSON), `version`. Rendered into the pinned notepad block. Compacted to `nodes.task_state` at run end.

### doc_drafts
`id`, `chat_id`, `name`, `spec` (JSON block list with server-assigned block ids), `version`, `rendered_path`, `created_at`, `updated_at`.

### context_summaries (pruner cache)
`id`, `scope` (`history`), `target_id` (last covered node), `parent_summary_id`, `text`, `tokens`, `source_hash`, `created_at`. A summary "through node X" is valid for every path through X and extends the previous one; edits create new nodes, so stale summaries are unreachable from new branches.

---

## 6. Tree operations

| Operation | Effect |
|---|---|
| Send | New user node under current leaf (completed assistant node or root) + assistant node + run |
| Edit | New user node as sibling of the edited one, attachments copied, new run |
| Retry | New assistant node as sibling of the existing one, new run from step 0 |
| Select | Set a parent's `selected_child_id`; no run |

All start operations go through one "start run" path guarded by the global lock. A cancelled run with partial output is kept as an assistant node (`status=cancelled`) so it can be retried; it cannot be a parent for new messages in v1.

---

## 7. Run lifecycle

**Attach (before send):** upload endpoint stores the file, hashes it, and the harness ingests it into the chat's data store (section 12). The attachment gets a handle (`f1`) and the UI shows a chip.

**Send:**
1. `POST` start validates, creates user node, assistant node and run row (snapshot, `launch_id`), returns `run_id`. The DB constraint enforces one active run.
2. Executor (asyncio task) emits `run_started`, builds context, builds a **fresh Strands agent**, streams, writes events and steps.
3. Frontend subscribes via SSE with replay. Disconnects never affect the run.
4. Completion writes final status, node finalization, compacted `task_state` and the terminal event in **one transaction**.
5. `POST /runs/{id}/cancel` is the only way to stop a run (section 9).
6. On backend startup, runs still `running`/`cancelling` become `interrupted`.

Process model: an asyncio task inside FastAPI is enough to survive frontend death. A separate worker process can come later behind the same executor interface.

---

## 8. Event contract

Envelope: `run_id`, `seq`, `ts`, `type`, `data`, `agent` (default `main`; reserved for sub-agents).

| Type | `data` |
|---|---|
| `run_started` | chat_id, user_node_id, assistant_node_id, origin, options, settings_snapshot |
| `context_built` | tokens_before, tokens_after, budget, pruned{...}, attachments[{id, mode}] |
| `context_summarizing` | target, status |
| `thinking_delta` | step_id, text |
| `text_delta` | step_id, text |
| `tool_call_started` | step_id, call_id, name, arguments |
| `tool_call_finished` | step_id, call_id, status (`ok`/`error`/`cancelled`), is_error, result_preview, result_truncated, object_id?, duration_ms |
| `step_finished` | step_id, kind, status, tokens |
| `skill_loaded` | name, tools[], body_tokens |
| `object_created` | id, kind, name, rows?, tokens, source_step |
| `scratch_updated` | plan, notes, version |
| `doc_rendered` | doc, path, attachment_id, checks |
| `usage` | prompt_tokens, completion_tokens, iteration |
| `warning` | code, message |
| `cancel_requested` | none |
| `run_completed` | finish_reason, usage_total, duration_ms |
| `run_failed` | error{code, message, retryable}, phase |
| `run_cancelled` | phase, partial |

Rules:
1. Exactly one terminal event per run; terminal event, run status and node finalization are one transaction.
2. `seq` is gap-free and monotonic per run from 1.
3. Deltas are coalesced (~50 ms or N chars) before being written.
4. Replay: SSE `id` = `seq`; on reconnect, subscribe to live first, then read missed rows, dedupe by seq.
5. In-progress steps exist only in events; the `steps` row is written at `step_finished`. On cancel/failure, partial steps are finalized from accumulated deltas with `status=partial`.
6. Stable error codes (`llama_unreachable`, `context_overflow`, `tool_failed`, `cancelled`, `internal`, ...).
7. Namespace `verification_*` is reserved for the future verification gate.

---

## 9. Strands translation layer

### Components
- **ContextBuilder**: DB path -> pruned Strands messages (pure function + cache reads).
- **RunExecutor**: owns one run: builds the agent, drives the stream, handles cancel and failure.
- **EventSink**: only writer of `run_events`; assigns `seq`; coalesces deltas; broadcasts.
- **ToolRuntime**: tool registry, skill loader, result offloader, argument validator.

Strands is **stateless per run**: a fresh `Agent` each run, `messages` from the built context, no Strands session manager. The DB is the source of truth.

### Model adapter
Built-in `LlamaCppModel` against the local llama-server. Sampling params (`top_k`, `top_p`, `temperature`, ...) go through `params`; it also supports `cache_prompt` and maps context overflow to `ContextWindowOverflowException`. Multimodal requires llama-server started with `--mmproj`.

### Mapping output to events
| Source | Used for |
|---|---|
| `agent.stream_async(...)` events (text, reasoning via `reasoningText`, tool events) | live preview: `text_delta`, `thinking_delta` |
| Hook events (before/after invocation, model call, tool call, message added) | structural truth: steps, `tool_call_*`, `step_finished`, `usage` |

Steps are built from **complete messages**, not reassembled deltas. Hooks are bundled into one plugin/hook-provider ("RunEvents") per run. Strands supports `HookProvider` and `Plugin`/`@hook`; callbacks may be async; ordering via `HookOrder`; per-run context via `invocation_state`.

### Hooks (day one)
- **Before tool call**: emit `tool_call_started`; validate arguments (existence of ids/columns, size cap); check cancel; can veto a call (`cancel_tool`) — the verification gate will live here.
- **After tool call (ResultOffloader)**: modifies the result before the model sees it (supported by Strands). Small results pass through; larger results are written to the data store and replaced by a preview + id (section 10). Also emits `tool_call_finished`, sets `is_error` from `result.status`/`exception`. `retry` is available for transient tool failures.
- **Before/after model call**: usage, timing, injecting the notepad block (needs spike S10), loop detection. After-model-call `retry` can absorb transient llama-server failures.
- **Loop detector**: identical call repeated, or the same error twice, injects a short nudge ("same call as before; try a different approach") and records a one-line error summary.

### Execution limits
Use Strands' native per-invocation `limits` (turns, total tokens, output tokens). Exhausted limits surface as stop reasons (e.g. `limit_turns`); map them to a `warning` plus `run_completed` with that `finish_reason`. Token limits are checked between turns.

### Cancellation
`agent.cancel()` exists (thread-safe, idempotent, stop reason `cancelled`, checked at checkpoints such as the top of each loop cycle).
1. API sets run status `cancelling`, emits `cancel_requested`.
2. Executor calls `agent.cancel()` **and** cancels its asyncio task so the in-flight HTTP stream to llama-server is closed (spike S3 confirms what each does).
3. Running tools get an optional `cancel()` (subprocess tools killed explicitly; renders write to a temp file and rename atomically).
4. `finally`: finalize in-progress steps as `partial`, write `cancelled` + `run_cancelled` atomically, release the lock.
Cancel during a tool call is the case most likely to leak; test it first.

### Failure
Same `finally` path with `run_failed` and a coded error; mapping from exceptions to codes lives in one function. Backend crash: startup marks leftover active runs `interrupted` and finalizes empty assistant nodes.

---

## 10. Context management

### Principle: control plane vs data plane
The model works on the **control plane**: short commands, schemas, previews, notes and the prose it must write itself. All bulk data lives in the **data plane** (the chat's data store), where deterministic code operates on it. Rows never pass through the model in either direction.

### Regions and budget (32k window; starting values, tune on real runs)
| Region | Tokens | Rule |
|---|---|---|
| Fixed: system prompt + tool definitions | ~3-4k | never pruned |
| Pinned: goal, notepad (plan + notes), loaded skill bodies | ~3k | never pruned during the task |
| Conversation history (older turns, summarized) | ~5k | summarized, cached |
| Rolling window of recent tool steps | ~11k | verbatim while recent |
| **Generation reserve** (thinking + answer) | ~8k | never spent on prompt |
| Headroom | ~2k | |

Thinking consumes the same window within a step, so the generation reserve is explicit.

### Result offloading (pruning by construction)
Every tool result passes through the ResultOffloader:
- **≤ ~400 tokens**: passes through unchanged.
- **Larger**: full body stored in the data store (table object in DuckDB, text object in SQLite), and the model receives a compact reply: preview (head/first rows), shape/size, id, and the next action, e.g. `[r7] 340 rows × 6 cols, 8.1k tokens. Preview: ... Use show(r7, ...) or query on r7.`
- **Per-result hard cap**: ~1.5k tokens of anything that is shown inline.
- **Query results are always saved** as objects (auto id `r1`, `r2`, or `save_as`) and only *displayed* if they fit the display budget (~400 tokens, TSV, with shape and a truncated flag). Saving is cheap, so the model never has to decide whether to save.

### Demotion inside the current turn
Nothing in the current turn is deleted, but results are **demoted**: once the rolling window is full, the oldest results are replaced in context by one-line stubs (`[r7: read f1 p1-3, 2.1k tokens — show(r7) to re-read]`). The model's own text and the user's prompt are never stubbed.
**Exception:** large authored arguments (e.g. a long `doc_text`) are replaced by a stub after the call succeeds (`[wrote 1.1k tokens to block b4 of d1]`), since the draft already holds the content. Needs spike S13; fallback is to keep arguments small by writing documents in sections of ≤ ~300 tokens.

### Pass by reference
- Tool arguments over ~800 tokens are rejected: "pass data by reference (result id or SQL), don't inline it."
- Tools that move data (`doc_table`, `doc_chart`, export) take `source` = result id or alias, never rows.

### Older turns (completed)
Applied by the ContextBuilder when the prompt crosses the threshold:
1. System prompt: never touched, always first.
2. Tool calls stripped from older turns; results replaced by stubs (tool calls and results stay **paired**: strip both and leave a summary inside the assistant message; never leave an orphan).
3. Tool **errors** keep a one-line summary so the model can see repeated failures and avoid loops.
4. Older user/assistant exchanges fold into a running summary (cached in `context_summaries`, written by the local model in a separate non-agent call), rather than being dropped.
5. `thinking` steps are never replayed.

### Hysteresis and the prompt cache
Pruning that rewrites old content invalidates llama-server's prompt cache from that point. So prune in batches: when prompt tokens cross ~75% of the prompt budget (window minus generation reserve), compact down to ~50% in one go. Summaries are cached so the prefix stays byte-stable across retries and later turns. The notepad block changes every step, so it is placed **after** the stable history, near the end of the prompt; only it and new tokens are re-prefilled each step. Token estimates can use llama-server's `/tokenize`.

### Notepad (working memory)
Structured, per run, stored in `scratch_state`:
- `plan`: ≤ 12 items, each `pending | doing | done`.
- `notes`: ≤ 20 items, each short text + optional reference (`r3`, `f1 §2`). **Facts and decisions go in notes; data goes in tables.**
- Hard caps return errors ("notepad full 20/20, merge or remove a note"), not silent truncation. Rendered block ≤ ~1.5k tokens, pinned.
- At run end it is compacted into `nodes.task_state` (plan, notes, active skills) and pinned again in the next run of that chat, so follow-ups continue instead of restarting.

---

## 11. Tool ecosystem

### 11.1 Principles
1. Small uniform surface: always-on core of ~11 tools, consistent argument names and result shapes.
2. **Handles, not paths.** Files are `f1`, results `r7`, drafts `d1`. The model never types a filename.
3. **Validate, then teach.** Check arguments against schemas and real state; errors list valid options (`sheet "Q5" not found; available: Q1..Q4`).
4. Results are context spend: every tool has a result budget, compact formats (TSV), and pagination with cursors.
5. Reads are always safe and cacheable; writes go to a versioned workspace and are where verification attaches.
6. Capability grows by adding skills, not by growing the always-on tool list.

### 11.2 Core (always-on) tools
| Tool | Purpose |
|---|---|
| `list_files()` | attachments and outputs of this chat |
| `outline(handle)` | structure: pages, headings, sheets with row counts, token counts per section |
| `read(handle, section / pages / cursor)` | structure-aware read, ~1k tokens per page by default |
| `search(target, query)` | FTS5 keyword search over a file handle or a text object; returns snippets with locations |
| `describe(id)` | schema, 5 sample rows, stats, data-quality warnings for tables; summary for files/drafts |
| `query(sql, save_as?)` | read-only SQL over all tables; result always saved; displayed only if small |
| `show(id, rows/cols/offset or range/cursor)` | paginated view of any stored object (replaces `recall`) |
| `collect(table, rows)` | append a few structured rows (extracted from prose) to a named collector table; first call fixes the schema |
| `plan(items)`, `note(text, ref?)` | notepad |
| `load_skill(name)` | load a skill (section 11.5) |

### 11.3 Data store (DuckDB)
- One file per chat: `workspace/<chat_id>/data.duckdb`.
- Attached spreadsheets/CSVs become tables (`f1_Jan` ...). Sheets with the same header signature are also exposed as one unified view with a `_sheet` column (DuckDB `UNION ALL BY NAME`). Sheets that do not match are listed separately in `describe`.
- Type inference and data-quality warnings are recorded at ingestion ("revenue has 2 non-numeric values in Mar").
- `query` runs on a **read-only connection** with a timeout and a cap on materialized rows.
- Tables embedded in Word/PDF files are extracted and registered as tables too (`f1_t3`), so `query` works on them.
- `collect` is how repeated facts from many prose documents become a table instead of loose notes.
- Data store contents are deleted with the chat.

### 11.4 Prose documents (Word, PDF)
Extraction at attach time produces: a structure outline, text chunks split on structural boundaries (never mid-paragraph) with locations (`§3.2`, `p.14`) indexed in FTS5, and embedded tables registered in DuckDB. Scanned PDFs use OCR/vision only for pages with no extractable text. Long-document summarization is map-reduce through sub-agents (one clean window per section, short summary back to the parent) — a later roadmap item.

### 11.5 Skills (the extension mechanism)
A skill is a folder:
```
skills/<name>/
  SKILL.md     frontmatter (name, one-line description), short body (<= ~500 tokens)
  tools.py     tool functions with typed schemas, short descriptions
  scripts/     tested helper scripts
```
- The system prompt contains only the **catalog**: name + one line per skill.
- `load_skill(name)` returns the skill body as a tool result and **activates its tools** for the rest of the task. `skill_loaded` is emitted. Loaded skill bodies are pinned.
- `active_skills` is stored in `task_state`, so follow-up runs in the same chat re-activate them.
- Skill bodies are mostly "call this tool/script with these arguments"; the scripts are written and tested by us, so the model supplies data and parameters, never library calls.
- Loading adds tool definitions near the top of the prompt, which invalidates the prompt cache once. That happens early in the task when the context is small, so the cost is small. Whether Strands can add tools between steps of a running loop is spike S9; fallback is a generic `run_skill(skill, action, args)` executor.
- Adding pptx later = adding a folder.

### 11.6 The docx skill
A document is a **draft** (data structure in `doc_drafts`); the `.docx` is a build artifact. Tools:

| Tool | Arguments | Notes |
|---|---|---|
| `doc_new` | name, template? | creates draft `d1` |
| `doc_text` | doc, kind (`heading`/`paragraph`/`list`), text, level? | the only place the model writes prose; sections ≤ ~300 tokens |
| `doc_table` | doc, source, columns?, formats?, caption? | `source` = result id/alias; data pulled at render |
| `doc_chart` | doc, source, type, x, y, title, axis labels | PNG via matplotlib |
| `doc_edit` | doc, block_id, fields / `remove` / `move_to` | block ids are server-assigned |
| `doc_render` | doc, path | writes `outputs/<name>.docx`, returns the verification report |

Validation at call time: `doc_chart` checks that source exists, `x`/`y` are real columns, `y` is numeric, categories ≤ ~30 (otherwise suggests top-N). Rendering (python-docx + matplotlib) writes to a temp file and renames atomically; the output is registered as an attachment (handle `f2`), so the user gets a file card.

### 11.7 Verification report (seed of the verification gate)
`doc_render` returns: row/column counts of each table block, the data source of each chart, and a **numbers-in-prose check**: every number found in paragraph text is matched against values in the referenced tables (with rounding tolerance); unmatched numbers are reported with the nearest candidates. It also compares plan items marked done against the document's actual content. Later this moves into a `BeforeToolCall`/render hook with `verification_*` events.

---

## 12. Attachments and ingestion

Ingestion runs at **attach time** (not run time) and is cached by content hash + extractor version, so retries never re-extract.
- **Spreadsheets/CSV**: loaded into DuckDB tables; unified view; quality warnings. (Verify DuckDB's xlsx reading in your version; fallback is openpyxl/pandas into DuckDB.)
- **Word/PDF/text**: outline + FTS5 chunks + embedded tables (11.4).
- **Images**: image block if `supports_vision`, otherwise skipped with a `warning`.
- **Large documents**: never inlined. The user message carries a one-line description (`[f1: sales.xlsx, 12 sheets, 1,248 rows — use describe(f1)]`); content is reached only through tools.
- Attachments on older user nodes keep the mode recorded at extraction time, so history is stable across retries.

---

## 13. Worked example: "From sales.xlsx (12 monthly sheets), build report.docx with a monthly-totals table, a bar chart and a 3-sentence summary."

**Attach:** file saved, hashed, ingested: tables `f1_Jan..f1_Dec`, unified view `f1_all`, warning "revenue has 2 non-numeric values in Mar". Handle `f1`.

**Send:** `POST /chats/{id}/messages` -> user node, assistant node, run, `run_id` returned; SSE opens. Initial context ≈ 4k tokens: system prompt (with skill catalog), core tool definitions, empty notepad, the user message with the one-line attachment description.

**Loop** (each step: model reads the whole context, replies with a tool call or final answer; harness runs it and appends the result):

| # | Model call | Result (approx.) |
|---|---|---|
| 1 | `plan([...4 items])` | `plan saved` |
| 2 | `load_skill("docx-report")` | skill body (~400 tok); doc tools activated |
| 3 | `describe("f1")` | schema, unified view, 5 sample rows, warning (~300 tok) |
| 4 | `query("SELECT _sheet AS month, SUM(revenue) AS total FROM f1_all GROUP BY 1 ...", save_as="monthly")` | `[monthly] 12 rows × 2 cols` + the rows (~150 tok) |
| 5 | `doc_new("report")` | `created d1` |
| 6 | `doc_text(d1, heading, ...)` | `ok, block b1` |
| 7 | `doc_table(d1, source="monthly", caption=...)` | `ok, block b2: table 12×2` |
| 8 | `doc_chart(d1, source="monthly", type="bar", x="month", y="total")` | `ok, block b3` |
| 9 | `doc_text(d1, paragraph, "<3 sentences>")` | `ok, block b4` |
| 10 | `doc_render(d1)` | `saved outputs/report.docx; table matches monthly; chart source monthly; numbers in text: 3/3 found` |
| 11 | final text | run ends |

Total tool traffic ≈ 2k tokens; peak context ≈ 6-7k of 32k. The 12 sheets never enter the context; at step 7 the model said "put `monthly` here" instead of retyping 12 rows.

**Failure paths:** a 500-row query shows 10 rows + id `r3`; a typo'd column returns an error listing valid columns; a repeated identical call triggers the loop nudge; cancel aborts the model request, saves the partial step and ends the run as cancelled.

**After:** one transaction writes final status, steps, assistant node, compacted `task_state`; `report.docx` is registered as `f2`. A follow-up ("make the chart horizontal") starts a new run; the data store still holds `monthly` and draft `d1`, the notepad summary is pinned again, so the model edits the chart block and re-renders.

---

## 14. API surface

| Endpoint | Purpose |
|---|---|
| `POST /chats/{id}/attachments` | upload + ingest; returns handle |
| `POST /chats/{id}/messages` | send (text, attachment ids, options) -> `run_id` or 409 |
| `POST /nodes/{id}/edit` | edit user node -> `run_id` or 409 |
| `POST /nodes/{id}/retry` | retry (new assistant sibling) -> `run_id` or 409 |
| `POST /nodes/{id}/select` | switch version via `selected_child_id` |
| `GET /chats/{id}/tree` | visible path + sibling counts |
| `GET /chats/{id}/objects` | catalog (tables, drafts, outputs) for later UI |
| `GET /runs/active` | the single active run, if any |
| `GET /runs/{id}` | status snapshot |
| `GET /runs/{id}/events?after=seq` | SSE with replay |
| `POST /runs/{id}/cancel` | cancel |
| `GET/PUT /settings` | read/write settings; reports restart-needed keys |

---

## 15. Evaluation switches (for the paper)
Each mechanism can be a switch: result offloading, notepad, hysteresis pruning, verification report, skills vs always-on tools. This lets the ablation configurations in the research proposal be run without rewriting the harness.

---

## 16. Spike checklist (do before building)

Version: assume the latest release; the newest changelog entry found was Python `strands-agents` 1.55.0 (2026-09-08); repository is now `strands-agents/harness-sdk`. Pin the installed version and re-run the spike on upgrades.

**Confirmed from the docs**
- `stream_async` yields text, tool, lifecycle and reasoning events (`reasoning`, `reasoningText`) and a final `result`.
- Hook events: before/after invocation, before/after model call (`exception`, `retry`), before/after tool call (`cancel_tool`, `selected_tool`, `interrupt`, `exception`, `retry`, modifiable `result`). `HookProvider` and `Plugin`/`@hook` supported; async callbacks; `HookOrder`.
- `agent.cancel()` exists; native per-invocation limits (turns, total tokens, output tokens).
- `LlamaCppModel` exists with `params` incl. `top_k`, `cache_prompt`; overflow mapped to `ContextWindowOverflowException`.

**To verify with a script (one agent, one tool, print every stream and hook event)**
- S1: whether `chat_template_kwargs: {enable_thinking: ...}` passes through `LlamaCppModel.params` (else subclass or patch the request body).
- S2: whether llama-server reasoning arrives separately (maps to `reasoningText`) or inline in text (then split on think tags).
- S3: what `agent.cancel()` interrupts mid-generation vs task cancellation; confirm llama-server frees the slot when the connection closes.
- S4: name/timing of the message-added hook; whether it fires for tool-result messages.
- S5: shape of tool errors (`result.status`, `exception`) for `is_error`.
- S6: where token usage comes from per model call.
- S7: `Agent(messages=...)` accepts reconstructed history with tool-use/tool-result pairs for the model's chat template.
- S8: dependency compatibility: clean venv with FastAPI, uvicorn, pydantic, httpx, DuckDB, python-docx, matplotlib, SQLite layer; check required Python version on PyPI; commit a lockfile.
- S9: can tools be added to a running agent between loop steps (skill activation)? Fallback: `run_skill`.
- S10: can a before-model-call hook modify the messages/prompt for that call (notepad injection)? Fallback: append the block to the last user message.
- S11: modifying `event.result` in the after-tool-call hook is reflected in what the model sees (docs say yes).
- S12: DuckDB reading `.xlsx` in the installed version, and `UNION ALL BY NAME` across sheets.
- S13: can large tool-call arguments in the history be replaced with a stub after success?
- S14: does Strands' newer context-offloading support (listed in the 1.55 changelog) overlap with our ResultOffloader, and can we reuse it?

---

## 17. Roadmap and open topics

1. **RAG-like retrieval across documents (to design next).** Currently covered: single-document retrieval (`outline`/`read`/`search` with FTS5). Not yet covered: a persistent library searched across chats, semantic (embedding) search, hybrid ranking, citations, index freshness.
2. **Factual memory (to design next).** What is remembered about the user and past tasks, how it is stored, retrieved and kept out of the way of the context budget.
3. Verification gate (hooks + `verification_*` events) on top of the render report.
4. Sub-agents as child runs (`parent_run_id`, `agent` field in the envelope), including map-reduce over long documents.
5. More skills (pptx, pdf forms); optional code-runner escape hatch with a pre-tested helper library.
6. Automations: scheduler creating runs without a frontend (supported as is).
7. Optional: separate worker process, event compaction after terminal state, checkpoint/resume (out of scope today).

## 18. Open questions
- Cancelled partial answer as a parent for new messages? (Currently no.)
- Event retention: keep everything in v1; compact deltas after terminal state later?
- Thinking toggle when `supports_thinking` is false: hide or disable?
- Per-result display budget and window split need tuning against real runs.
