# Atlas on Strands: Architecture, Tool Ecosystem and Skills

Status: design agreed through 2026-10-09. Scope: backend chat pipeline, run engine, ingestion, tool ecosystem, skills, context management. Frontend rebuild comes later.
Still open (do not block the base): persistent-library RAG and factual memory (section 17).
Next step: start at Layer 0 of the layer-by-layer build sequence (section 19). Spike items are now attached to the layer where they matter (section 16) instead of all being done up front.

Changes since the 2026-10-08 version:

* **Skills now use Strands' built-in `AgentSkills` plugin** (section 11.5). It provides the SKILL.md format, the catalog in the system prompt and the `skills(skill\_name=...)` activation tool, but it does *not* bundle tools. So our skill tools are registered up front, and a before-tool-call hook gates them until the skill has been activated. The dynamic tool-activation mechanisms (A/B/C), the `load\_skill` tool and LRU eviction are removed; they remain only as a scaling escape hatch.
* **Granite-Docling (VLM) is an optional second Docling pipeline** (section 12): `standard` pipeline by default for born-digital documents, `vlm` for scanned/hard pages, served by a local llama.cpp server on CPU. The default is decided by spike S15 on real documents.
* **Thinking:** passed per request through llama.cpp's extra request arguments (per the Unsloth llama.cpp notes); S1 is reduced to a confirmation.
* **Section 19 rewritten** as a layer-by-layer build sequence with interfaces, tests and spikes per layer; section 16 spikes are now assigned to layers.

Changes in the 2026-10-08 version:

* **Ingestion generalized (sections 11.3, 11.4, 12):** Docling is the parser for all document types; spreadsheets/CSV use a direct tabular reader; every parser returns the same `IngestResult` contract. Summaries are generated lazily.
* **Storage routing rule (11.3):** decided by the *kind* of output an ingestor produces, never by guessing content. Tables -> DuckDB, text/outline/vectors -> SQLite, ambiguous tables stored in both.
* **Retrieval index (5, 11.4):** new `chunks` table with FTS5 and vectors; `search` is hybrid (keyword + vector) once vectors exist.
* **Skills spec (11.5) rewritten in full:** package format, tool and error contracts, lifecycle, activation fallbacks, trust model, testing, v1 skill set.
* **Draft SDK (11.6):** `doc\_drafts` generalized to `drafts` (kind = docx, pptx, ...); event `doc\_rendered` renamed `draft\_rendered`.
* **API (14):** attachment status endpoint; sending with an unfinished attachment is rejected.
* **Spikes S15-S19 added (16); build order added (19).**

\---

## 1\. Goals and non-goals

**Goals**

* A solid chat pipeline: prompt + attachments + a few toggles in, streamed agent output out.
* Edit-prompt and retry, with every version kept and browsable via `<` `>`.
* Every turn runs as an isolated **run** that keeps going if the frontend disconnects or dies.
* Force-stop (cancel) of a running inference without restarting any server.
* **Reliable everyday document and data tasks on a small local model** (Gemma-class, 32k window, \~70-90 tok/s). Reliability comes from the harness, not from asking the model to recall library syntax.
* A foundation that accepts new capabilities (pptx, pdf forms, ...) by adding skills, plus sub-agents, verification gating and automations later, without schema changes.

**Non-goals (for now)**

* Runtime model swapping, token-budget thinking control, run queueing, mid-run checkpoint/resume, multi-user, model-authored skills.

\---

## 2\. Decisions log

|Topic|Decision|
|-|-|
|Launch|One CLI starts client, FastAPI and llama-server from `settings.json`. Force-quitting the CLI kills all.|
|Model|One model, fixed at launch. No swapping.|
|Thinking|Boolean `thinking`, not token budgets. Hidden if the model has no thinking support. Sent per request as an extra argument (`chat\_template\_kwargs.enable\_thinking`), so toggling needs no restart.|
|Settings|`settings.json` is the single source of truth. Per-message input exposes only toggles (currently `thinking`).|
|Setting tiers|**Restart-needed**: model, context size, GPU layers, ports, embedding model. **Live**: top\_p, top\_k, temperature, system prompt, thinking default. Live settings apply from the next run.|
|App state and text index|SQLite (WAL, foreign keys on): app state, chunks, FTS5, vectors.|
|Data store|**DuckDB**, one file per chat, for tables and analysis.|
|**Storage routing**|By the *kind of output* an ingestor/tool produces: tables -> DuckDB; text, outline, vectors, app state -> SQLite. Ambiguous tables are stored in both. The model never chooses a store; it chooses a tool.|
|**Parsing**|**Docling** for all document types (PDF, DOCX, PPTX, HTML, images, markdown). Spreadsheets/CSV use a direct tabular reader. One shared `IngestResult` contract. For PDFs/images two pipelines sit behind one setting: `standard` (layout + table models, copies the embedded text layer) and `vlm` (Granite-Docling 258M served locally).|
|**Retrieval**|Hybrid: FTS5 keyword + vector similarity on CPU embeddings; keyword-only until vectors are ready.|
|**Summaries**|Outline and token counts are free at ingest; document/section summaries are generated lazily on first need and cached.|
|Concurrency|One active run globally. No queue. 409 on a second start. Send button disabled while a run is active. Ingestion runs in a separate single worker and is independent of the run lock.|
|Branching|Message tree. Edit = sibling user node. Retry = sibling assistant node (new run).|
|Retry|Restarts from step 0. No checkpoints. Interrupted/failed/cancelled runs are recovered by retrying.|
|Cancel|Required in v1.|
|Extension mechanism|**Skills**, using Strands' built-in `AgentSkills` plugin for the SKILL.md format, the catalog and activation. Our tools live beside the skill (`tools.py`), are registered up front and are gated until the skill is activated. Document capabilities (docx now, pptx later) are skills. The model does not know whether a capability is built-in.|
|Always-on tools|Only universal basics: file/data access, notepad, and the built-in `skills` tool.|
|Charts|Rendered as images (PNG) in v1.|
|Data passing|**By reference.** The model never retypes bulk data; tools take result ids or SQL.|
|Context window|32k. Budget split in section 10.|
|Attachments|All document types in v1.|

\---

## 3\. Process model and CLI

Three child processes supervised by the CLI, plus one optional on-demand ingest server:

1. **llama-server**: spawned with restart-tier settings; the CLI waits for `/health`.
2. **FastAPI backend**: owns SQLite, DuckDB files, the run executor, event streaming, and the ingest worker (a separate process pool of size 1 inside the backend, so Docling never blocks the event loop).
3. **Client dev/static server**.
4. **Ingest VLM server (optional, on demand)**: a second llama-server serving Granite-Docling (GGUF + its projector file), started by the ingest worker only when a document needs the `vlm` pipeline and stopped after an idle timeout. CPU by default (`ingest.vlm.gpu\_layers = 0`) so Gemma keeps the VRAM. It is a child of the same process group, so force-quit still cleans it up.

CLI responsibilities:

* Read and validate `settings.json`, spawn, prefix and stream logs.
* Write `launched.json` (restart-tier values actually used + a `launch\_id`). The backend compares it to `settings.json` to show "restart required".
* On exit/force-quit, kill the whole process group (Windows: job object). Test early that no orphaned llama-server keeps VRAM.

Per-chat workspace on disk: `workspace/<chat\_id>/{data.duckdb, uploads/, scratch/, outputs/}`.

\---

## 4\. Settings

|Key|Tier|
|-|-|
|model path/name, context size, GPU layers, ports, `supports\_thinking`, `supports\_vision`, `embedding.model`, `embedding.enabled`, `ingest.vlm.model\_path`, `ingest.vlm.gpu\_layers`|restart|
|top\_p, top\_k, temperature, system prompt, default `thinking`, pruning thresholds, per-result token cap, display budget, max tool iterations, `skills.dirs`, `skills.pinned\_token\_cap` (default 2000), `ingest.device` (default cpu), `ingest.docling.pipeline` (standard / vlm / auto; default decided by spike S15)|live|

* A run **snapshots** resolved live settings (`runs.settings\_snapshot`) and records the `launch\_id`.
* Per-message options are validated against an allowlist (`thinking` only). Unknown keys return 422.
* UI edits to restart-tier keys write the file and show "restart required". Changing `embedding.model` also requires re-embedding (vectors record the model id; mismatches are detected and re-queued).

\---

## 5\. Data model (SQLite, app state and text index)

Conventions: ULID primary keys, integer epoch-ms timestamps, JSON as TEXT.

### chats

`id`, `title`, `root\_id` (FK nodes), `created\_at`, `updated\_at`, `deleted\_at`.

### nodes (the tree)

|Column|Notes|
|-|-|
|id|PK|
|chat\_id|FK|
|parent\_id|FK nodes; null only for root|
|role|`root`, `user`, `assistant`|
|content|user: JSON blocks (text, attachment refs). assistant: null (content in `steps`)|
|run\_id|assistant only; FK runs; unique|
|selected\_child\_id|which child the UI shows|
|task\_state|assistant only: JSON {plan, notes, active\_skills} compacted at run end|
|created\_at|sibling order|

* Synthetic `root` node per chat, so editing the first message is an ordinary sibling operation.
* Visible path = root, then `selected\_child\_id` to the leaf. Switching versions = update one `selected\_child\_id`.
* New user messages attach only to root or to an assistant node whose run is `completed`.
* Assistant node is created at run start. System prompt is not in the tree (comes from the snapshot).

### steps

`id`, `node\_id`, `idx`, `kind` (`thinking` | `text` | `tool\_call` | `tool\_result`), `content` (JSON), `call\_id`, `is\_error`, `status` (`complete` | `partial`), `tokens`, `object\_id` (for tool results that were offloaded).
For offloaded results, `content` holds the preview shown to the model and `object\_id` points at the full body. The context builder reads only `steps`, skips `thinking`.

### runs

`id`, `chat\_id`, `user\_node\_id`, `assistant\_node\_id`, `origin` (`send`/`retry`/`edit`), `status` (`running`/`cancelling`/`completed`/`failed`/`cancelled`/`interrupted`), `options`, `settings\_snapshot`, `launch\_id`, `error`, `usage`, `context\_stats`, `last\_seq`, `started\_at`, `finished\_at`.
**Global lock:** a partial unique index over a constant expression for rows with status `running` or `cancelling`; a second concurrent start fails the constraint and becomes 409.

### run\_events

PK (`run\_id`, `seq`); `ts`, `type`, `payload`. Append-only replay log.

### Attachments and ingestion

* `attachments`: id, sha256, original\_name, mime, size, storage\_path, handle, created\_at (deduped by hash).
* `node\_attachments`: node\_id, attachment\_id, position. Copied to the new user node on edit unless removed.
* `attachment\_extractions`: attachment\_id, `parser` (`docling` | `tabular` | `text`), `parser\_version`, `docling\_pipeline` (`standard` | `vlm` | null), `status` (`queued` | `running` | `ready` | `failed`), `progress` (0-1), `embed\_status` (`none` | `pending` | `ready` | `failed`), `embed\_model`, `outline` (JSON), `table\_ids` (JSON), `warnings` (JSON), `token\_count`, `page\_count`, `doc\_json\_path` (the saved Docling document, so re-chunking never re-parses), `error`. Unique on (attachment\_id, parser, parser\_version, docling\_pipeline).
* `chunks`: id, attachment\_id, extraction\_id, `scope` (`chat`; `library` reserved for later), idx, `kind` (`text` | `table\_text` | `schema` | `caption`), `section\_path`, `location` (JSON: page, heading path), `text`, `tokens`.

  * FTS5 virtual table `chunks\_fts(text, section\_path)` over `chunks`.
  * Vector table `chunk\_vectors(chunk\_id, embedding)`: `sqlite-vec` virtual table, with a fallback of BLOB + brute-force cosine in numpy (fine for tens of thousands of chunks). Spike S16.
* `attachment\_summaries`: attachment\_id, `section\_path` (null = whole document), `text`, `tokens`, `model\_id`, `created\_at`. Filled lazily (section 12).

### Catalog and objects

* `catalog\_objects`: id, chat\_id, run\_id, step\_id, node\_id, name, kind (`table` | `text` | `file` | `draft` | `image`), `store` (`duckdb` | `sqlite` | `disk`), schema (JSON), row\_count, tokens, provenance (the SQL/tool call that produced it), created\_at.
* `text\_objects`: object\_id, body, plus an **FTS5** index over it (text tool results).
* Objects are **immutable**: nothing is edited in place; a derived object is created instead. Every number therefore has recorded lineage.
* **Branch visibility:** tools resolve an object id only if it is an attachment of the current chat or was created by a node on the current path.

### scratch\_state

`run\_id`, `plan` (JSON), `notes` (JSON), `active\_skills` (JSON list of skill names activated in this run; restored into the fresh agent at the start of the next run), `version`. Rendered into the pinned notepad block. Compacted to `nodes.task\_state` at run end.

### drafts

`id`, `chat\_id`, `kind` (`docx` | `pptx` | ...), `name`, `spec` (JSON block list with server-assigned block ids), `version`, `rendered\_path`, `created\_at`, `updated\_at`. (Generalizes the earlier `doc\_drafts`; see the Draft SDK in 11.6.)

### context\_summaries (pruner cache)

`id`, `scope` (`history`), `target\_id` (last covered node), `parent\_summary\_id`, `text`, `tokens`, `source\_hash`, `created\_at`. A summary "through node X" is valid for every path through X and extends the previous one; edits create new nodes, so stale summaries are unreachable from new branches.

\---

## 6\. Tree operations

|Operation|Effect|
|-|-|
|Send|New user node under current leaf (completed assistant node or root) + assistant node + run|
|Edit|New user node as sibling of the edited one, attachments copied, new run|
|Retry|New assistant node as sibling of the existing one, new run from step 0|
|Select|Set a parent's `selected\_child\_id`; no run|

All start operations go through one "start run" path guarded by the global lock, and reject with 422 `attachment\_not\_ready` if any attached file is not `ready`. A cancelled run with partial output is kept as an assistant node (`status=cancelled`) so it can be retried; it cannot be a parent for new messages in v1.

\---

## 7\. Run lifecycle

**Attach (before send):** upload endpoint stores the file, hashes it, creates the attachment with status `queued` and returns its handle (`f1`) immediately. The ingest worker processes it (section 12); the UI polls the status and shows progress on the chip.

**Send:**

1. `POST` start validates, creates user node, assistant node and run row (snapshot, `launch\_id`), returns `run\_id`. The DB constraint enforces one active run.
2. Executor (asyncio task) emits `run\_started`, restores `active\_skills` from the previous `task\_state`, builds context, builds a **fresh Strands agent**, streams, writes events and steps.
3. Frontend subscribes via SSE with replay. Disconnects never affect the run.
4. Completion writes final status, node finalization, compacted `task\_state` and the terminal event in **one transaction**.
5. `POST /runs/{id}/cancel` is the only way to stop a run (section 9).
6. On backend startup, runs still `running`/`cancelling` become `interrupted`; ingest jobs still `running` are re-queued.

Process model: an asyncio task inside FastAPI is enough to survive frontend death. A separate worker process for runs can come later behind the same executor interface.

\---

## 8\. Event contract

Envelope: `run\_id`, `seq`, `ts`, `type`, `data`, `agent` (default `main`; reserved for sub-agents).

|Type|`data`|
|-|-|
|`run\_started`|chat\_id, user\_node\_id, assistant\_node\_id, origin, options, settings\_snapshot|
|`context\_built`|tokens\_before, tokens\_after, budget, pruned{...}, attachments\[{id, mode}]|
|`context\_summarizing`|target, status|
|`thinking\_delta`|step\_id, text|
|`text\_delta`|step\_id, text|
|`tool\_call\_started`|step\_id, call\_id, name, arguments|
|`tool\_call\_finished`|step\_id, call\_id, status (`ok`/`error`/`cancelled`), is\_error, result\_preview, result\_truncated, object\_id?, duration\_ms|
|`step\_finished`|step\_id, kind, status, tokens|
|`skill\_loaded`|name, tools\[], body\_tokens (emitted by a hook when the built-in `skills` tool is called)|
|`object\_created`|id, kind, name, rows?, tokens, source\_step|
|`scratch\_updated`|plan, notes, version|
|`draft\_rendered`|draft, kind, path, attachment\_id, checks\[{name, status, detail}]|
|`usage`|prompt\_tokens, completion\_tokens, iteration|
|`warning`|code, message (codes include `attachment\_skipped`, `limit\_turns`, `skill\_stubbed`)|
|`cancel\_requested`|none|
|`run\_completed`|finish\_reason, usage\_total, duration\_ms|
|`run\_failed`|error{code, message, retryable}, phase|
|`run\_cancelled`|phase, partial|

Rules:

1. Exactly one terminal event per run; terminal event, run status and node finalization are one transaction.
2. `seq` is gap-free and monotonic per run from 1.
3. Deltas are coalesced (\~50 ms or N chars) before being written.
4. Replay: SSE `id` = `seq`; on reconnect, subscribe to live first, then read missed rows, dedupe by seq.
5. In-progress steps exist only in events; the `steps` row is written at `step\_finished`. On cancel/failure, partial steps are finalized from accumulated deltas with `status=partial`.
6. Stable error codes (`llama\_unreachable`, `context\_overflow`, `tool\_failed`, `cancelled`, `internal`, ...).
7. Namespace `verification\_\*` is reserved for the future verification gate.

Ingestion is outside any run, so it has no event stream in v1; the UI polls `GET /attachments/{id}`.

\---

## 9\. Strands translation layer

### Components

* **ContextBuilder**: DB path -> pruned Strands messages (pure function + cache reads).
* **RunExecutor**: owns one run: builds the agent, drives the stream, handles cancel and failure.
* **EventSink**: only writer of `run\_events`; assigns `seq`; coalesces deltas; broadcasts.
* **ToolRuntime**: tool registry (core + skill tools), `AgentSkills` wiring and the skill gate, result offloader, argument validator.

Strands is **stateless per run**: a fresh `Agent` each run, `messages` from the built context, no Strands session manager. The DB is the source of truth.

### Model adapter

Built-in `LlamaCppModel` against the local llama-server. Sampling params (`top\_k`, `top\_p`, `temperature`, ...) go through `params`; it also supports `cache\_prompt` and maps context overflow to `ContextWindowOverflowException`. Multimodal requires llama-server started with `--mmproj`.

### Mapping output to events

|Source|Used for|
|-|-|
|`agent.stream\_async(...)` events (text, reasoning via `reasoningText`, tool events)|live preview: `text\_delta`, `thinking\_delta`|
|Hook events (before/after invocation, model call, tool call, message added)|structural truth: steps, `tool\_call\_\*`, `step\_finished`, `usage`|

Steps are built from **complete messages**, not reassembled deltas. Hooks are bundled into one plugin/hook-provider ("RunEvents") per run. Strands supports `HookProvider` and `Plugin`/`@hook`; callbacks may be async; ordering via `HookOrder`; per-run context via `invocation\_state`.

### Hooks (day one)

* **Before tool call**: emit `tool\_call\_started`; validate arguments (existence of ids/columns, size cap); **skill gate**: if the tool belongs to a skill (listed in its `allowed-tools`) that is not activated in this run, veto it with `error\[not\_loaded]: skill "X" is not activated; call skills(skill\_name="X") first`; check cancel; can veto a call (`cancel\_tool`) — the verification gate will live here.
* **After tool call (ResultOffloader)**: modifies the result before the model sees it (supported by Strands). Small results pass through; larger results are written to the data store and replaced by a preview + id (section 10). Also emits `tool\_call\_finished`, sets `is\_error` from `result.status`/`exception`. `retry` is available for transient tool failures.
* **Before/after model call**: usage, timing, injecting the notepad block (needs spike S10), loop detection. After-model-call `retry` can absorb transient llama-server failures.
* **Loop detector**: identical call repeated, or the same error twice, injects a short nudge ("same call as before; try a different approach") and records a one-line error summary.
* **Skill state hooks**: before invocation, write the previous run's `active\_skills` into the fresh agent's skill state (the `AgentSkills` plugin keeps activation in `agent.state`; spike S9); after a call to the `skills` tool, emit `skill\_loaded`, record the skill in `scratch\_state.active\_skills`, and mark the result as pinned for the ContextBuilder.

### Execution limits

Use Strands' native per-invocation `limits` (turns, total tokens, output tokens). Exhausted limits surface as stop reasons (e.g. `limit\_turns`); map them to a `warning` plus `run\_completed` with that `finish\_reason`. Token limits are checked between turns.

### Cancellation

`agent.cancel()` exists (thread-safe, idempotent, stop reason `cancelled`, checked at checkpoints such as the top of each loop cycle).

1. API sets run status `cancelling`, emits `cancel\_requested`.
2. Executor calls `agent.cancel()` **and** cancels its asyncio task so the in-flight HTTP stream to llama-server is closed (spike S3 confirms what each does).
3. Running tools see `ctx.cancel\_token` set; subprocess tools are killed explicitly; renders write to a temp file and rename atomically.
4. `finally`: finalize in-progress steps as `partial`, write `cancelled` + `run\_cancelled` atomically, release the lock.
Cancel during a tool call is the case most likely to leak; test it first.

### Failure

Same `finally` path with `run\_failed` and a coded error; mapping from exceptions to codes lives in one function. Backend crash: startup marks leftover active runs `interrupted` and finalizes empty assistant nodes.

\---

## 10\. Context management

### Principle: control plane vs data plane

The model works on the **control plane**: short commands, schemas, previews, notes and the prose it must write itself. All bulk data lives in the **data plane** (the chat's data store and text index), where deterministic code operates on it. Rows never pass through the model in either direction.

### Regions and budget (32k window; starting values, tune on real runs)

|Region|Tokens|Rule|
|-|-|-|
|Fixed: system prompt + tool definitions (core + skill tools)|\~4-5k|never pruned|
|Pinned: goal, notepad (plan + notes), loaded skill bodies|\~3k|never pruned during the task|
|Conversation history (older turns, summarized)|\~5k|summarized, cached|
|Rolling window of recent tool steps|\~10k|verbatim while recent|
|**Generation reserve** (thinking + answer)|\~8k|never spent on prompt|
|Headroom|\~2k||

Thinking consumes the same window within a step, so the generation reserve is explicit.

Skill instructions arrive as the result of the built-in `skills` tool, so they are ordinary tool results that the offloader and demotion rules must **not** touch (pinned). Pinned skill bodies are capped at `skills.pinned\_token\_cap` (\~2k tokens) in total; if the cap is exceeded the oldest body is replaced by a stub (`\[skill X loaded earlier - call skills(skill\_name="X") to re-read]`).

### Result offloading (pruning by construction)

Every tool result passes through the ResultOffloader:

* **<= \~400 tokens**: passes through unchanged.
* **Larger**: full body stored in the data store (table object in DuckDB, text object in SQLite), and the model receives a compact reply: preview (head/first rows), shape/size, id, and the next action, e.g. `\[r7] 340 rows x 6 cols, 8.1k tokens. Preview: ... Use show(r7, ...) or query on r7.`
* **Per-result hard cap**: \~1.5k tokens of anything that is shown inline.
* **Query results are always saved** as objects (auto id `r1`, `r2`, or `save\_as`) and only *displayed* if they fit the display budget (\~400 tokens, TSV, with shape and a truncated flag). Saving is cheap, so the model never has to decide whether to save.

### Demotion inside the current turn

Nothing in the current turn is deleted, but results are **demoted**: once the rolling window is full, the oldest results are replaced in context by one-line stubs (`\[r7: read f1 p1-3, 2.1k tokens - show(r7) to re-read]`). The model's own text and the user's prompt are never stubbed.
**Exception:** large authored arguments (e.g. a long `doc\_text`) are replaced by a stub after the call succeeds (`\[wrote 1.1k tokens to block b4 of d1]`), since the draft already holds the content. Needs spike S13; fallback is to keep arguments small by writing documents in sections of <= \~300 tokens.

### Pass by reference

* Tool arguments over \~800 tokens are rejected: "pass data by reference (result id or SQL), don't inline it."
* Tools that move data (`doc\_table`, `doc\_chart`, `export\_table`) take `source` = result id or alias, never rows.

### Older turns (completed)

Applied by the ContextBuilder when the prompt crosses the threshold:

1. System prompt: never touched, always first.
2. Tool calls stripped from older turns; results replaced by stubs (tool calls and results stay **paired**: strip both and leave a summary inside the assistant message; never leave an orphan).
3. Tool **errors** keep a one-line summary so the model can see repeated failures and avoid loops.
4. Older user/assistant exchanges fold into a running summary (cached in `context\_summaries`, written by the local model in a separate non-agent call), rather than being dropped.
5. `thinking` steps are never replayed.

### Hysteresis and the prompt cache

Pruning that rewrites old content invalidates llama-server's prompt cache from that point. So prune in batches: when prompt tokens cross \~75% of the prompt budget (window minus generation reserve), compact down to \~50% in one go. Summaries are cached so the prefix stays byte-stable across retries and later turns. The notepad block changes every step, so it is placed **after** the stable history, near the end of the prompt; only it and new tokens are re-prefilled each step. Token estimates can use llama-server's `/tokenize`.

### Notepad (working memory)

Structured, per run, stored in `scratch\_state`:

* `plan`: <= 12 items, each `pending | doing | done`.
* `notes`: <= 20 items, each short text + optional reference (`r3`, `f1 s2`). **Facts and decisions go in notes; data goes in tables.**
* Hard caps return errors ("notepad full 20/20, merge or remove a note"), not silent truncation. Rendered block <= \~1.5k tokens, pinned.
* At run end it is compacted into `nodes.task\_state` (plan, notes, active skills) and pinned again in the next run of that chat, so follow-ups continue instead of restarting.

\---

## 11\. Tool ecosystem

### 11.1 Principles

1. Small uniform surface: always-on core of 11 tools, consistent argument names and result shapes.
2. **Handles, not paths.** Files are `f1`, results `r7`, drafts `d1`. The model never types a filename.
3. **Validate, then teach.** Check arguments against schemas and real state; errors list valid options (`sheet "Q5" not found; available: Q1..Q4`).
4. Results are context spend: every tool has a result budget, compact formats (TSV), and pagination with cursors.
5. Reads are always safe and cacheable; writes go to a versioned workspace and are where verification attaches.
6. Capability grows by adding skills, not by growing the always-on tool list.
7. Skill tools are visible from the start (constant tool definitions keep the prompt prefix cacheable); the `skills` tool plus a gate make the model read a skill's instructions before using its tools.

### 11.2 Core (always-on) tools

|Tool|Purpose|
|-|-|
|`list\_files()`|attachments and outputs of this chat|
|`outline(handle)`|structure: pages, headings, sheets with row counts, token counts per section|
|`read(handle, section / pages / chunk / cursor)`|structure-aware read, \~1k tokens per page by default; `chunk` reads around a search hit|
|`search(target, query)`|`target` = a file handle, a text object id, or `all` (every attachment in this chat). Hybrid keyword + vector search when vectors are ready, keyword-only otherwise (the mode is not exposed to the model). Returns the top 5 snippets (<= \~80 tokens each) with location and chunk id|
|`describe(id)`|schema, 5 sample rows, stats, data-quality warnings for tables; summary for files/drafts|
|`query(sql, save\_as?)`|read-only SQL over all tables; result always saved; displayed only if small|
|`show(id, rows/cols/offset or range/cursor)`|paginated view of any stored object|
|`collect(table, rows)`|append a few structured rows (extracted from prose) to a named collector table; first call fixes the schema|
|`plan(items)`, `note(text, ref?)`|notepad|
|`skills(skill\_name)`|built-in tool of the Strands `AgentSkills` plugin: returns a skill's instructions and marks it activated (section 11.5)|

Which store a tool reads is fixed inside the tool: `outline`, `read`, `search` use the SQLite text index; `query`, `describe` (for tables) use DuckDB; `show` reads whatever store the object lives in (its catalog row says which).

### 11.3 Data store (DuckDB) and the routing rule

**Routing rule.** Where a piece of data is stored is decided by the *kind of output* the producing ingestor or tool declares, never by inspecting the content:

|Output kind|Store|Why|
|-|-|-|
|Tables (sheet, CSV, table found inside a document), query results, collector tables|DuckDB|data you compute over with SQL|
|Text chunks, outline, vectors, tool-result text|SQLite|search and lookup|
|Chats, runs, events, catalog, drafts, notepad|SQLite|app state|

**Ambiguous case:** a table inside a PDF/DOCX may be data or just layout. It is not classified. Every table Docling reports goes to DuckDB *and* its text rendering is added to `chunks` (kind `table\_text`), so both SQL and keyword/vector search can find it.

Details:

* One DuckDB file per chat: `workspace/<chat\_id>/data.duckdb`.
* Spreadsheets/CSVs become tables named `<handle>\_<sheet>` (sanitized). Sheets with the same header signature are also exposed as one unified view `<handle>\_all` with a `\_sheet` column (`UNION ALL BY NAME`). Sheets that do not match are listed separately in `describe`.
* Tables found inside documents are registered as `<handle>\_t<n>` (Docling table -> DataFrame -> DuckDB).
* Type inference and data-quality warnings are recorded at ingestion ("revenue has 2 non-numeric values in Mar").
* `query` runs on a **read-only connection** with a timeout and a cap on materialized rows.
* `collect` is how repeated facts from many prose documents become a table instead of loose notes.
* Data store contents are deleted with the chat.
* If files stay small, SQLite alone could do the same work; DuckDB is kept for direct xlsx/csv ingestion, type inference, `UNION ALL BY NAME` and friendlier date SQL. It is the one component to drop if a single engine is preferred later.

### 11.4 Retrieval index (prose)

Produced at ingest from the parser output:

* **Outline**: heading hierarchy (documents), sheet list with row counts (spreadsheets), token counts per section.
* **Chunks**: split on structural boundaries (never mid-paragraph; Docling's own hierarchical/hybrid chunkers are the first choice, spike S15), each with `section\_path` and `location` (`s3.2`, `p.14`), stored in `chunks`.
* **Keyword index**: FTS5 over `chunks`.
* **Vector index**: CPU embedding of each chunk into `chunk\_vectors`, computed as a second stage so keyword search is available first.
* **Schema chunks**: every table also gets one chunk describing its columns (kind `schema`), so `search` can find "revenue" even in a spreadsheet.
* Search fuses keyword and vector rankings (reciprocal rank fusion) and returns snippets with location and chunk id; `read(handle, chunk=...)` expands around a hit. Citations come for free from `location`.
* Long-document summarization is map-reduce through sub-agents (one clean window per section, short summary back to the parent) — roadmap item.

### 11.5 Skills (the extension mechanism)

**Built on Strands' `AgentSkills` plugin.** The plugin gives us, for free: the SKILL.md format (YAML frontmatter + markdown instructions), discovery from directories, a catalog injected into the system prompt (name + description per skill), an activation tool named `skills` (call: `skills(skill\_name="docx-report")`) that returns the full instructions, and activation state kept in `agent.state`. It does **not** register tools: skills are instruction packages, and the tools they refer to must be provided separately. The available skills can be swapped between invocations (`set\_available\_skills`) and the catalog is refreshed before each invocation. We build a fresh agent per run, so this fits.

**Our extension of the format.** A skill folder additionally carries `tools.py` (typed tool functions), `tests/` and `evals.yaml`. Everything else is the standard format, so instruction-only skills written by others (using only core tools) also load unchanged.

```
skills/<name>/                 # directory name must equal the skill name
  SKILL.md       frontmatter + short body (what the model sees on activation)
  tools.py       our tool functions (registered by ToolRuntime, not by Strands)
  scripts/       deterministic helpers called by tools.py (optional)
  tests/         fixtures + golden-output tests (required for skills with tools)
  evals.yaml     3-5 sample prompts for end-to-end runs with the real model (required)
```

Frontmatter (Strands-compatible):

```yaml
---
name: docx-report              # lowercase letters, digits, hyphens; 1-64 chars; equals the directory name
description: Build Word documents from tables, text and charts   # shown in the catalog; keep <= 100 chars
allowed-tools: doc\_new doc\_text doc\_table doc\_chart doc\_edit doc\_render
metadata:
  version: "1"
  outputs: docx
  needs: duckdb
---
```

`allowed-tools` is informational in Strands, but it is our source of truth for which tools belong to a skill (used by the gate and the linter). Our own fields live under `metadata` so the file stays valid for any Strands-compatible loader.

**Tool registration and the gate**

* All skill tools are registered when the agent is built, so tool definitions never change during a run. This keeps the prompt prefix cacheable and removes any need for runtime tool addition.
* Each skill tool's description starts with its skill tag (`\[docx-report] ...`).
* The before-tool-call **gate** vetoes a skill tool whose skill is not activated in this run: `error\[not\_loaded]: skill "docx-report" is not activated; call skills(skill\_name="docx-report") first`. This makes the model read the instructions before using the tools, which is what makes them reliable. Spike S20 measures how often a small model skips activation; if often, auto-activate on first use instead.
* **Budget rule:** all skill tool schemas together must stay <= \~2k tokens. If that is exceeded (many skills), switch on the escape hatch: register a skill's tools only after activation. That needs one of three mechanisms (add tools to the live agent between loop cycles; end the loop after `skills` and rebuild the agent with the new tool set; or one generic `run\_skill(skill, tool, args)` executor) and is deliberately not built in v1.

**Lifecycle**

1. **Startup:** `AgentSkills` loads `skills/` (and `skills.dirs`); our linter validates the skills; invalid skills are skipped with a warning, never a crash (do not use `strict=True` in production).
2. **Run start:** restore `active\_skills` from the previous `task\_state` into the fresh agent's skill state, so a follow-up does not re-activate (spike S9).
3. **Activation:** the model calls `skills(skill\_name=...)`. The result holds the instructions and a resource listing; set `max\_resource\_files` low, because our scripts are reached only through our tools. An after-tool-call hook emits `skill\_loaded`, records the skill in `scratch\_state.active\_skills` and pins the result (section 10).
4. **Run end:** `active\_skills` is compacted into `nodes.task\_state`.
5. The catalog entries include a `<location>` path to each SKILL.md. It is harmless because the model has no file tools; filter it out if a strict "handles, not paths" rule is wanted.

**Lint rules** (`atlas skills check`, at startup and in CI):

* body <= \~500 tokens; <= 6 tools per skill; all tool schemas of one skill <= \~900 tokens;
* <= 5 arguments per tool, flat (no nested objects), enums for fixed choices, ids as strings;
* tool descriptions <= \~40 tokens; tool names unique across all skills and the core (prefix by domain: `doc\_\*`, `slide\_\*`, `chart\_\*`);
* `name` matches the directory; every name in `allowed-tools` exists in `tools.py` and vice versa;
* tests and evals present.

**Tool contract.** Every tool returns either `ToolOutput(summary, objects, warnings)`, rendered as `ok: <summary>`; or `ToolError(code, message, valid)`, rendered as `error\[code]: message. valid: a, b, c`, with codes `not\_found`, `bad\_arg`, `too\_large`, `not\_ready`, `not\_loaded`, `failed`. Unexpected exceptions become `error\[internal]` with the traceback only in the log. Every tool receives a `ToolContext`: run id, workspace paths, read-only DuckDB connection, `ctx.resolve(id)` (enforces branch visibility), event emitter, cancel token, settings snapshot. The model supplies ids only; skills never receive raw paths from model arguments.

**Trust and safety.** v1 skills are first-party trusted code; the model cannot create or edit skills. No network unless a skill declares `needs: network` (reserved for the browser skill). Subprocess scripts run with a timeout and are killed on cancel; renders write to a temp file and rename atomically.

**Testing.** Unit tests with golden outputs (no model); `atlas skills check`; model-facing `evals.yaml` prompts run through the real pipeline, recording pass/fail, steps and tokens. A failing eval usually means the instructions or tool descriptions need work, not the model. These runs also feed the paper's ablations.

**Scaling notes.** The catalog costs \~25 tokens per skill, fine to \~15 skills; beyond that add `find\_skill(query)`. Skill-to-skill dependencies are out of scope in v1; shared code lives in `atlas/lib/` (charts, tables, the Draft SDK).

**v1 skill set**

|Skill|Tools|Purpose|
|-|-|-|
|`docx-report`|`doc\_new`, `doc\_text`, `doc\_table`, `doc\_chart`, `doc\_edit`, `doc\_render`|reference skill; template for all later authoring skills|
|`data-export`|`export\_table(source, format, name)`|csv / xlsx export of a result table (data never passes through the model)|
|`charts`|`chart\_make(source, type, x, y, title)`|standalone chart image objects|
|`pptx-deck` (next)|`slide\_\*`|same Draft SDK, different block types and renderer|

### 11.6 Draft SDK and the docx skill

Authoring skills share one harness-level **Draft SDK** so a new format only supplies block types and a renderer:

* A draft is a row in `drafts` (`kind`, `spec`, `version`); the output file is a build artifact.
* The skill registers **block types**, each with a JSON schema (docx: `heading`, `paragraph`, `list`, `table`, `chart`, `page\_break`). The SDK assigns block ids, validates every mutation against the schema and against referenced sources (existence, columns), and bumps `version`.
* `render(draft) -> (file, VerificationReport)`: writes a temp file, renames atomically, registers the output as an attachment (handle `f2`), emits `draft\_rendered`.
* `VerificationReport` is a list of checks `{name, status: ok|warn|fail, detail}`. Generic checks live in the SDK (sources exist, row/column counts match, numbers-in-prose, plan items marked done vs content); skills add format-specific checks.

The docx tools:

|Tool|Arguments|Notes|
|-|-|-|
|`doc\_new`|name, template?|creates draft `d1`|
|`doc\_text`|doc, kind (`heading`/`paragraph`/`list`), text, level?|the only place the model writes prose; sections <= \~300 tokens|
|`doc\_table`|doc, source, columns?, formats?, caption?|`source` = result id/alias; data pulled at render|
|`doc\_chart`|doc, source, type, x, y, title, axis labels|PNG via matplotlib (shared `atlas/lib/charts`)|
|`doc\_edit`|doc, block\_id, fields / `remove` / `move\_to`|block ids are server-assigned|
|`doc\_render`|doc, path|writes `outputs/<name>.docx`, returns the verification report|

Validation at call time: `doc\_chart` checks that source exists, `x`/`y` are real columns, `y` is numeric, categories <= \~30 (otherwise suggests top-N).

### 11.7 Verification report (seed of the verification gate)

The render step's `VerificationReport` includes a **numbers-in-prose check**: every number found in paragraph text is matched against values in the referenced tables (with rounding tolerance); unmatched numbers are reported with the nearest candidates. Later this moves into a `BeforeToolCall`/render hook with `verification\_\*` events.

\---

## 12\. Attachments and ingestion

**Pipeline:** upload -> hash and dedupe -> attachment row, extraction `queued`, handle returned -> ingest worker (single process, independent of the run lock) -> `ready`. The UI polls `GET /attachments/{id}` for `status`, `progress` and `embed\_status`. Sending a message while any attachment is not `ready` is rejected (422 `attachment\_not\_ready`). A failed ingest shows its error on the chip and can be retried or removed.

**Ingestors** (registry by MIME). All return the same `IngestResult`: `{outline, chunks, tables, warnings, page\_count, token\_count}`.

|Ingestor|Handles|Notes|
|-|-|-|
|`DoclingIngestor`|PDF, DOCX, PPTX, HTML, images, markdown|two pipelines for PDFs/images (below); DOCX/PPTX/HTML use Docling's own format backends; runs on CPU (`ingest.device`) to protect VRAM; saves the Docling document JSON to disk; tables -> DataFrames -> DuckDB; table text duplicated as chunks|
|`TabularIngestor`|XLSX, CSV, TSV|reads straight into DuckDB (no document model); type inference; unified view; warnings; outline = sheets with row counts; one schema chunk per table|
|`TextIngestor`|txt, md, json, log, code|paragraph-based chunking|

**Docling pipelines (PDFs and images).**

* `standard`: layout analysis + table-structure models + OCR where needed. For born-digital PDFs it copies the embedded text layer, so extracted text is verbatim (nothing is generated). Lighter on memory; the Docling docs suggest it for limited resources and batch work.
* `vlm`: Granite-Docling-258M (IBM, Apache 2.0) looks at each page as an image and generates DocTags, which Docling converts into the document model. Strong on scans, complex layouts, equations, code and chart-to-table, but it *generates* text (IBM notes that small models can hallucinate), and it is slower and heavier.
* `auto` (proposed default): `standard` first; use `vlm` for pages with no text layer or where layout analysis is unreliable. Spike S15 measures both on real documents and decides the default.
* The VLM runs in its own llama.cpp server (GGUF + projector file) and is called through Docling's remote-VLM option (`ApiVlmOptions` with `enable\_remote\_services=True`), so it never shares a process with Gemma. That the GGUF route works end to end with Docling's DocTags parsing is unverified (S15); the Docling VLM guide documents vLLM and Ollama servers, not llama.cpp.

Rules:

* **Routing by output kind** (11.3). The ingestor declares what it produced; nothing is classified by content.
* **Cache key:** (sha256, parser, parser\_version, docling\_pipeline, embed\_model). Retries and re-uploads never re-parse.
* **Two-stage readiness:** stage 1 (outline, chunks, FTS, DuckDB tables) makes the file `ready`; stage 2 (embeddings) continues in the background (`embed\_status`). `search` uses vectors only when complete.
* **Summaries are lazy:** outline and token counts are stored eagerly; a document or section summary is generated by the local model the first time a task needs it (map-reduce for long documents) and cached in `attachment\_summaries`.
* **Images:** passed as image blocks if `supports\_vision`, otherwise skipped with a `warning`; Docling OCR still indexes any text in them.
* **Large documents:** never inlined. The user message carries a one-line description (`\[f1: sales.xlsx, 12 sheets, 1,248 rows - use describe(f1)]`); content is reached only through tools.
* Attachments on older user nodes keep their recorded description, so history is stable across retries.
* Ingestion contention: one worker, CPU only. Expect seconds per PDF page on CPU; progress is reported per page.

\---

## 13\. Worked example: "From sales.xlsx (12 monthly sheets), build report.docx with a monthly-totals table, a bar chart and a 3-sentence summary."

**Attach:** file saved, hashed; `TabularIngestor` produces tables `f1\_Jan..f1\_Dec`, unified view `f1\_all`, warning "revenue has 2 non-numeric values in Mar", an outline of 12 sheets and 12 schema chunks. Status `ready`. Handle `f1`.

**Send:** `POST /chats/{id}/messages` -> user node, assistant node, run, `run\_id` returned; SSE opens. Initial context \~5k tokens: system prompt (with skill catalog), core and skill tool definitions (skill tools are visible from the start, \~1k), empty notepad, the user message with the one-line attachment description.

**Loop** (each step: model reads the whole context, replies with a tool call or final answer; harness runs it and appends the result):

|#|Model call|Result (approx.)|
|-|-|-|
|1|`plan(\[...4 items])`|`ok: plan saved`|
|2|`skills(skill\_name="docx-report")`|skill instructions (\~400 tok, pinned); the doc tools now pass the gate|
|3|`describe("f1")`|schema, unified view, 5 sample rows, warning (\~300 tok)|
|4|`query("SELECT \_sheet AS month, SUM(revenue) AS total FROM f1\_all GROUP BY 1 ...", save\_as="monthly")`|`\[monthly] 12 rows x 2 cols` + the rows (\~150 tok)|
|5|`doc\_new("report")`|`ok: created d1`|
|6|`doc\_text(d1, heading, ...)`|`ok: block b1`|
|7|`doc\_table(d1, source="monthly", caption=...)`|`ok: block b2, table 12x2`|
|8|`doc\_chart(d1, source="monthly", type="bar", x="month", y="total")`|`ok: block b3`|
|9|`doc\_text(d1, paragraph, "<3 sentences>")`|`ok: block b4`|
|10|`doc\_render(d1)`|`ok: saved outputs/report.docx; table matches monthly; chart source monthly; numbers in text: 3/3 found`|
|11|final text|run ends|

Total tool traffic \~2k tokens; peak context \~6-7k of 32k. The 12 sheets never enter the context; at step 7 the model said "put `monthly` here" instead of retyping 12 rows.

**Failure paths:** a 500-row query shows 10 rows + id `r3`; a typo'd column returns `error\[bad\_arg]` listing valid columns; a repeated identical call triggers the loop nudge; cancel aborts the model request, saves the partial step and ends the run as cancelled.

**After:** one transaction writes final status, steps, assistant node, compacted `task\_state` (including `active\_skills`); `report.docx` is registered as `f2`. A follow-up ("make the chart horizontal") starts a new run; the data store still holds `monthly` and draft `d1`, the docx skill is re-activated automatically, the notepad summary is pinned again, so the model edits the chart block and re-renders.

**Prose variant:** for twelve PDF reports instead of sheets, steps 3-4 become `outline`/`search`/`read` per report plus `collect("monthly", \[...])`; everything from step 5 on is identical.

\---

## 14\. API surface

|Endpoint|Purpose|
|-|-|
|`POST /chats/{id}/attachments`|upload; returns handle and `status=queued` immediately|
|`GET /attachments/{id}`|status, progress, `embed\_status`, warnings, outline|
|`POST /attachments/{id}/retry`|re-run a failed ingest|
|`POST /chats/{id}/messages`|send (text, attachment ids, options) -> `run\_id`, 409 (run active) or 422 (`attachment\_not\_ready`)|
|`POST /nodes/{id}/edit`|edit user node -> `run\_id` or 409|
|`POST /nodes/{id}/retry`|retry (new assistant sibling) -> `run\_id` or 409|
|`POST /nodes/{id}/select`|switch version via `selected\_child\_id`|
|`GET /chats/{id}/tree`|visible path + sibling counts|
|`GET /chats/{id}/objects`|catalog (tables, drafts, outputs) for later UI|
|`GET /runs/active`|the single active run, if any|
|`GET /runs/{id}`|status snapshot|
|`GET /runs/{id}/events?after=seq`|SSE with replay|
|`POST /runs/{id}/cancel`|cancel|
|`GET /skills`|catalog (name, description, tools)|
|`GET/PUT /settings`|read/write settings; reports restart-needed keys|

\---

## 15\. Evaluation switches (for the paper)

Each mechanism can be a switch: result offloading, notepad, hysteresis pruning, verification report, skills vs always-on tools, hybrid vs keyword-only search. This lets the ablation configurations in the research proposal be run without rewriting the harness. Skill `evals.yaml` files double as task fixtures.

\---

## 16\. Spike checklist (attached to build layers)

Version: assume the latest release; the newest changelog entry found was Python `strands-agents` 1.55.0 (2026-09-08); repository is now `strands-agents/harness-sdk`. Pin the installed version and re-run the checks on upgrades. Each item is answered in the layer shown, with a small script, and the answer is written back into this section.

**Confirmed from the docs**

* `stream\_async` yields text, tool, lifecycle and reasoning events (`reasoning`, `reasoningText`) and a final `result`.
* Hook events: before/after invocation, before/after model call (`exception`, `retry`), before/after tool call (`cancel\_tool`, `selected\_tool`, `interrupt`, `exception`, `retry`, modifiable `result`). `HookProvider` and `Plugin`/`@hook` supported; async callbacks; `HookOrder`; `AfterInvocationEvent.resume`.
* `agent.cancel()` exists; native per-invocation limits (turns, total tokens, output tokens).
* `LlamaCppModel` exists with `params` incl. `top\_k`, `cache\_prompt`; overflow mapped to `ContextWindowOverflowException`.
* `AgentSkills` plugin: `from strands import Agent, AgentSkills, Skill`; sources are paths, URLs or `Skill` objects; constructor options `state\_key`, `max\_resource\_files`, `strict`; activation tool `skills(skill\_name=...)`; `get\_available\_skills`, `set\_available\_skills`, `get\_activated\_skills(agent)`; activation state in `agent.state`; catalog refreshed before each invocation; it does not register tools; `allowed-tools` is informational.
* Docling VLM pipeline: `VlmPipeline` with `VlmPipelineOptions`; remote OpenAI-compatible server through `ApiVlmOptions(url, model, api\_key)` with `enable\_remote\_services=True`; Granite-Docling-258M outputs DocTags. The Docling VLM guide does not document the llama.cpp/GGUF route; the model card says quantized builds for llama.cpp/Ollama/LM Studio exist but gives no instructions.

**Resolved by you:** thinking can be passed per request as an extra request argument (Unsloth's llama.cpp notes); S1 is now a confirmation only.

|ID|Question|Layer|If it fails|
|-|-|-|-|
|S1|Does the extra-argument route (`chat\_template\_kwargs.enable\_thinking`) work through the model adapter, per request, without restart?|L0|subclass the model or patch the request body|
|S2|Does llama-server return reasoning separately (maps to `reasoningText`) or inline in the text?|L0|split on the think tags ourselves|
|S3|What does `agent.cancel()` interrupt mid-generation vs asyncio task cancellation? Does llama-server free the slot when the connection closes?|L3|cancel both; use llama-server's slot API|
|S4|Name and timing of the message-added hook; does it fire for tool-result messages?|L3|build steps from the final `result.messages`|
|S5|Shape of tool errors (`result.status`, `exception`) for `is\_error`|L3|wrap tools so they always return a status|
|S6|Where token usage per model call comes from|L0|llama-server's `usage` field and `/tokenize`|
|S7|Does `Agent(messages=...)` accept a reconstructed history with tool-use/tool-result pairs for the model's chat template?|L0|normalize the history to the format the template expects|
|S8|Dependency compatibility: clean venv with FastAPI, uvicorn, pydantic, httpx, DuckDB, Docling, python-docx, matplotlib, sqlite-vec, an embedding runtime; Python version; commit a lockfile|L0|pin older versions; isolate Docling in its own environment/process|
|S9|`AgentSkills` state: what is stored in `agent.state\[state\_key]`; can we write it before the first invocation to restore activation; can a hook read `get\_activated\_skills(agent)`; does a low `max\_resource\_files` suppress the resource listing; does the `skills` result reach hooks as an ordinary tool result (needed to pin it)?|L7|keep our own activation list and inject it into the instructions|
|S10|Can a before-model-call hook change the prompt for that call (notepad injection)?|L6|append the block to the last user message|
|S11|Is a modified `event.result` (after-tool-call hook) what the model sees? (docs say yes)|L5|wrap tools instead of hooking|
|S12|DuckDB reading `.xlsx` in the installed version; `UNION ALL BY NAME` across sheets|L4a|openpyxl/pandas into DuckDB|
|S13|Can large tool-call arguments in the history be replaced with a stub after success?|L6|keep arguments small (<= \~300 tokens per call)|
|S14|Does Strands' newer context-offloading support (1.55 changelog) overlap our ResultOffloader?|L5|keep ours|
|S15|Docling on your machine: confirmed formats; CPU seconds per page for `standard` vs `vlm` on three documents (born-digital PDF with tables, scanned PDF, DOCX); tables to DataFrames; chunker quality; Granite-Docling GGUF + projector served by llama-server and consumed through `ApiVlmOptions` (does DocTags parsing work end to end?). Decide the default pipeline|L4c, L4e|`standard` only; add `vlm` later or only for scans|
|S16|`sqlite-vec` loads in your Python build (extension loading is disabled in some builds)|L4d|BLOB vectors + brute-force numpy cosine|
|S17|Embedding model choice and chunks per second on the i5|L4d|smaller model; embed lazily on first search|
|S18|Slowdown of Gemma's tok/s while ingestion and embedding run on CPU|L4|throttle the worker; pause ingestion during a run|
|S19|Quality of lazy summaries from the local model on a 20-page document (map-reduce)|L6|use summaries only for routing, never as facts|
|S20|Skill gate end to end: the veto message is returned and the small model recovers by calling `skills`; how often does it skip activation?|L7|auto-activate on first use of a gated tool|

### L0 answers (2026-10-10)

Environment: Python 3.12.10, `strands-agents==1.58.0` (newer than the 1.55.0 noted above; pin this and re-run these checks on upgrade), llama.cpp `b11429-d81235049`, model `unsloth\_e2b\_qat.gguf` (Gemma 3 2B e2b, Q4\_0), 32k ctx, 4 slots, served on port 8080. Scripts: `spikes/raw\_probe.py` (raw HTTP), `spikes/s1\_thinking.py`, `spikes/s7\_history.py`; fixture `scripts/smoke\_llamacpp.py`.

|ID|Answer|Consequence|
|-|-|-|
|S1|**Yes, with one fix.** The server accepts `chat\_template\_kwargs.enable\_thinking` per request. But `LlamaCppModel.\_format\_request` forwards `params` through a strict allowlist (`openai\_params` + `llamacpp\_specific\_params`) that does **not** contain `chat\_template\_kwargs`, so it is silently dropped.|Subclass the model (`atlas/models/llamacpp\_atlas.py`, the spec's "subclass the model or patch the request body" fallback). `set\_thinking(True/False)` flips it on a live instance; no restart, no new agent.|
|S2|**The server separates it; the Strands adapter throws it away.** llama-server returns Gemma 3's `<\|channel\|>thought` block as a separate `reasoning\_content` field (and `delta.reasoning\_content` when streaming) — it is not inlined in `content`. But upstream `stream()` only reads `delta.content` and `delta.tool\_calls`, so the reasoning was discarded, even though `\_format\_chunk` already knows how to emit `reasoningContent`.|Our adapter re-implements the SSE loop to forward `reasoning\_content`, opening/closing a reasoning block around the text. `reasoningText` events now reach the agent, which is what makes `thinking\_delta` (section 8) implementable. Delete our `stream()` when upstream fixes this.|
|S6|**Two places.** Per-call usage rides in the trailing SSE frame as `usage` (`prompt\_tokens`, `completion\_tokens`, `total\_tokens`, `prompt\_tokens\_details.cached\_tokens`); upstream already sets `stream\_options.include\_usage` and drains it into a `metadata` chunk → `usage: {inputTokens, outputTokens, totalTokens, cacheReadInputTokens}`. Independent of that, `count\_tokens` hits llama-server's `/tokenize` (needs `use\_native\_token\_count=True`), otherwise it falls back to estimation.|Feed the `usage` event straight from the metadata chunk. `cacheReadInputTokens` is a free measurement of how much of the prompt prefix llama.cpp reused — use it to validate the hysteresis pruning in L6 (section 10).|
|S7|**Yes, as-is.** `Agent(messages=...)` accepts a history containing `toolUse` / `toolResult` pairs. Verified by capturing a real tool-calling transcript, round-tripping it through JSON, and seeding a fresh agent: the model recovered the stored result and answered correctly. Shapes: assistant message holds `{"toolUse": {toolUseId, name, input}}`; the tool result is a **user** message holding `{"toolResult": {toolUseId, status, content:\[{text}]}}`.|The ContextBuilder can rebuild context straight from `steps` rows with no normalization step. Keep call/result pairing intact — the chat template needs both.|
|S8|**No conflict.** A clean install resolves 99 packages (150 installed) on Python 3.12.10: `docling 2.137.0` (pulls `torch 2.14.1`, `transformers 5.19.0`), `duckdb 1.5.6`, `pandas 3.0.6`, `sqlite-vec 0.1.9`, `fastembed 0.9.0` (ONNX, keeps the embedding runtime off the torch path), `python-docx 1.2.0`, `matplotlib 3.11.2`, `fastapi 0.143.0`. `pip check` is clean.|One environment is enough; Docling does not need isolating. Committed as `requirements.in` (intent) + `requirements.lock.txt` (resolved).|

Two findings that change earlier assumptions:

1. **The server defaults thinking ON.** Omitting `chat\_template\_kwargs` yields reasoning, so Atlas must send `enable\_thinking` explicitly on every request rather than relying on the server default. The live `thinking` setting must therefore always be materialised into the request.
2. **A before-model-call hook cannot swap the prompt directly.** `BeforeModelCallEvent` exposes `agent`, `invocation\_state`, `projected\_input\_tokens` and `cancel` — there is no `messages` field to replace. It does expose `projected\_input\_tokens` for free. This leans toward the S10 fallback ("append the block to the last user message"); resolve it in L6.

Also confirmed for later layers: `BeforeToolCallEvent` carries `tool\_use`, `selected\_tool` and `cancel\_tool` (so the L7 skill gate can veto), and `AfterToolCallEvent` carries a modifiable `result` plus `duration` (so L5's ResultOffloader has a seam).

Still open at L0: nothing outstanding. L1 (launcher and settings) is next.

\---

## 17\. Roadmap and open topics

1. **RAG over a persistent library (to design; does not block the base).** The base already contains the pieces: the same ingest pipeline and `chunks`/FTS5/vector tables with `scope='library'` reserved. Remaining design: library management, re-indexing when source files change, cross-chat search permissions, citation format in answers.
2. **Factual memory (to design).** What is remembered about the user and past tasks, who writes it, how it is retrieved without eating the context budget, how mistakes are corrected. Likely reuses the SQLite/FTS5/vector machinery.
3. Verification gate (hooks + `verification\_\*` events) on top of the render report.
4. Sub-agents as child runs (`parent\_run\_id`, `agent` field in the envelope), including map-reduce over long documents.
5. More skills (pptx, pdf forms, browser); optional code-runner escape hatch with a pre-tested helper library.
6. Automations: scheduler creating runs without a frontend (supported as is).
7. Optional: separate worker process for runs, event compaction after terminal state, checkpoint/resume (out of scope today).

## 18\. Open questions

* Cancelled partial answer as a parent for new messages? (Currently no.)
* Event retention: keep everything in v1; compact deltas after terminal state later?
* Thinking toggle when `supports\_thinking` is false: hide or disable?
* Per-result display budget, window split, `skills.pinned\_token\_cap` and the chunk size need tuning against real runs.
* Ingestion events: polling is enough for v1; add an SSE stream later if the UI needs it.
* Default Docling pipeline for PDFs (`standard`, `vlm` or `auto`): decided by spike S15 on real documents.

\---

## 19\. Build sequence (layer by layer)

**Ground rules**

* Each layer is runnable and testable on its own; a layer never imports from a higher one.
* Use a scripted `FakeModel` (returns canned text and tool calls) for every test that does not need the real model, so tests are deterministic and need no GPU. The real model is used for smoke tests and evals only.
* Spikes are answered inside the layer that needs them (section 16), and the answer is written back into this doc.
* Keep a log of real-model runs from the start (prompt, steps, tokens, outcome); it is the raw data for the paper.

**Suggested repository shape**

```
atlas/
  cli/        launcher, settings
  core/       sqlite schema + repos, tree ops, events
  run/        context\_builder, executor, event\_sink, hooks
  ingest/     worker, ingestors/, chunking, embedding
  tools/      runtime, offloader, core\_tools/
  skillrt/    AgentSkills wiring, gate, Draft SDK
  lib/        charts, tables
skills/       built-in skills (docx-report/, data-export/, charts/)
tests/
```

**Dependencies:** L0 -> L1 -> L2 -> L3; L2 -> L4; (L3 + L4) -> L5 -> L6; L5 -> L7 -> L8. L4 is independent of L3, so it can be built in either order or in parallel.

### L0 Smoke test (about half a day)

* **Build:** pinned virtual environment + lockfile; hand-start llama-server with your model; a \~60-line script with a Strands agent, `LlamaCppModel` and one dummy tool that prints every stream and hook event.
* **Answers:** S1, S2, S6, S7, S8.
* **Done when:** thinking toggles per request without a restart; you know where reasoning and usage appear; a reconstructed history with a tool call/result pair is accepted; the lockfile resolves with Docling, DuckDB, FastAPI, python-docx and matplotlib installed together. Keep the script as the first test fixture.

### L1 Launcher and settings

* **Build:** `settings.json` schema with tiers and a validator; CLI that spawns llama-server (waits for `/health`), the backend and the client; `launched.json` with `launch\_id`; process-group / job-object kill; restart-required diff.
* **Interface to the next layer:** a `Settings` object (restart part + live part) and `launch\_id`.
* **Tests:** killing the CLI leaves no orphan processes and frees VRAM; editing a restart-tier key shows "restart required"; invalid settings fail fast with a clear message.
* **Done when:** `atlas up` and Ctrl+C are reliable on both Windows and Linux.

### L2 Persistence core (no model involved)

* **Build:** SQLite schema + migrations (section 5); repository layer for chats, the node tree (send / edit / retry / select, visible path), runs with the partial-unique-index lock, `run\_events` append with `seq`, and a catalog stub.
* **Interface:** `Repo.start\_run(...)`, `Repo.visible\_path(chat)`, `Repo.append\_event(...)`, `Repo.finalize\_run(...)` (single transaction).
* **Tests:** sibling counts after edit and retry; `selected\_child` traversal; a second concurrent `start\_run` fails and maps to 409; `seq` stays gap-free under concurrent appends; `finalize\_run` is atomic (inject a failure mid-transaction); startup recovery marks leftover runs `interrupted`.
* **Done when:** the tree, lock and event tests are green. This layer pays back the most per hour of effort, so write it carefully before any agent code.

### L3 Run engine without tools (the "basic chat pipeline")

* **Build:** ContextBuilder v0 (path -> messages, thinking skipped, no pruning), RunExecutor (fresh agent per run), EventSink (coalescing, broadcast), SSE endpoint with replay, step-building hooks, cancel, failure mapping, and the endpoints `messages`, `edit`, `retry`, `select`, `cancel`, `runs/active`, `tree`.
* **Answers:** S3, S4, S5 (with a dummy tool).
* **Tests (FakeModel):** the run survives a dropped SSE connection; replay has no gaps and no duplicates; cancel mid-stream gives status `cancelled`, a saved partial step and a released lock; a model error gives `run\_failed`; a simulated crash gives `interrupted` after restart; 409 on a second start. **Real-model smoke:** five turns, edit turn 2, retry turn 3, switch branches, and check that the context sent to the model is correct for each branch.
* **Done when:** you can chat through curl or a bare test page with edit, retry and cancel working and branch contexts correct.

### L4 Ingestion (independent of L3)

* **4a Tabular:** `TabularIngestor`, DuckDB tables, unified view, quality warnings, attachment endpoints and the single-worker queue (S12).
* **4b Text:** `TextIngestor`, `chunks` table, FTS5.
* **4c Docling `standard`:** outline, chunks, tables -> DuckDB, table text chunks (S15 part 1).
* **4d Embeddings:** second-stage embedding and hybrid search (S16, S17).
* **4e Granite-Docling VLM (optional, may slip):** on-demand llama-server, `auto` policy, decide the default pipeline (S15 part 2, S18).
* **Interface:** `IngestResult`, `search\_chunks(target, query)`, `outline(handle)`, the DuckDB table registry.
* **Tests:** `sales.xlsx` -> 12 tables + unified view + warnings; a 50-page PDF -> outline and chunks, and `search` finds known phrases with the right page; a DOCX table appears as a DuckDB table and a `table\_text` chunk; re-upload is a cache hit; an ingest failure shows on the attachment; an unfinished attachment blocks send.
* **Done when:** a corpus of about ten sample files (xlsx, csv, born-digital pdf, scanned pdf, docx, pptx, txt) ingests with sensible outline, chunks and tables, and per-file timings are recorded.

### L5 Tool runtime and core tools

* **Build:** `ToolContext`, `ToolOutput`/`ToolError`, argument validators with "valid options" errors, ResultOffloader (S11, S14), the core data tools (`list\_files`, `outline`, `read`, `search`, `describe`, `query`, `show`, `collect`, `plan`, `note`), catalog with branch visibility, notepad state, and `AgentSkills` wired with an empty test skill so the `skills` tool exists.
* **Tests:** golden tests per tool; results over \~400 tokens are offloaded and recoverable through `show`/`query`; every error lists valid options; SQL is read-only (DROP, ATTACH and COPY fail) with timeouts; branch visibility holds.
* **Done when:** with the real model, "what is the total revenue in March?" and "where does the contract mention termination?" complete using only core tools.

### L6 Context management

* **Build:** regions and budgets, demotion with stubs, hysteresis pruning, history-summary cache, loop detector, notepad injection (S10), authored-argument stubs (S13), pinned-result exemption for skill bodies, lazy summaries (S19).
* **Tests:** a synthetic 40-step run stays under 75% of the prompt budget; the prompt prefix is byte-stable between consecutive steps (assert on the actual request bodies); tool calls and results are never orphaned; summaries are cached across retries; the loop detector fires on a repeated identical call.
* **Done when:** a deliberately long task (about twelve chained queries plus three document reads) completes within 32k with the real model and `context\_built` events show what was pruned.

### L7 Skills and authoring

* **Build:** skill gate hook, `active\_skills` restore (S9, S20), `atlas skills check` linter, Draft SDK, `docx-report` skill with the verification report, outputs registered as attachments.
* **Tests:** golden docx renders (open with python-docx and check the blocks); the gate's veto message; a follow-up run reuses the activation; the sales example end to end with the real model, 10 repeats.
* **Done when:** the success rate on the sales example is recorded and every failure is categorized (tool misuse, wrong query, unclear instructions, harness bug). Fix instructions and tool descriptions first, harness second.

### L8 More skills, evals, hardening

* **Build:** `data-export`, `charts`, an evals runner over every skill's `evals.yaml`, linter in CI; then `pptx-deck`.
* **Done when:** `atlas skills check` is clean and there is an eval report per skill.

### After the base

Persistent-library RAG, factual memory, sub-agents, the verification gate, automations (section 17).

