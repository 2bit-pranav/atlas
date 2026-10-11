# Atlas on Strands: Chat and Run Architecture

Status: design agreed 2026-10-06. Scope: backend chat pipeline only (frontend rebuild comes later).
Next milestone: Strands spike (section 13), then schema + executor.

---

## 1. Goals and non-goals

**Goals**
- A solid basic chat pipeline: prompt + attachments + a few toggles in, streamed agent output out.
- Edit-prompt and retry, with all versions kept and browsable via `<` `>`.
- Every turn runs as an isolated **run** that keeps going if the frontend disconnects or dies.
- Force-stop (cancel) of a running inference without restarting any server.
- A foundation that later accepts tools with hooks, sub-agents, verification gating, and automations without schema changes.

**Non-goals (for now)**
- Model swapping at runtime, token-budget thinking control, run queueing, mid-run checkpoint/resume, multi-user.

---

## 2. Decisions log

| Topic | Decision |
|---|---|
| Launch | One CLI starts three processes (client, FastAPI, llama-server) from `settings.json`. Force-quitting the CLI kills all. |
| Model | One model, fixed at launch. No model dropdown, no swapping. |
| Thinking | Boolean `thinking` (on/off), not token budgets. Hidden if the model has no thinking support. |
| Settings | `settings.json` is the single source of truth. Per-message input exposes only toggles (currently `thinking`). |
| Setting tiers | **Restart-needed**: model, context size, GPU layers, ports. **Live**: top_p, top_k, temperature, system prompt, thinking default. Live settings apply from the next run. |
| Storage | SQLite (WAL, foreign keys on). |
| Concurrency | Exactly one active run globally. No queue. Second start returns 409. Send button disabled while a run is active. |
| Branching | Tree of messages. **Edit** creates a sibling user node. **Retry** creates a sibling assistant node (new run). |
| Retry semantics | Always restarts from step 0. No internal checkpoints. An interrupted/failed/cancelled run is recovered by retrying. |
| Cancel | Required in v1. |
| Pruning | System prompt never pruned. Tool calls stripped from older turns. Tool results dropped if the reply already carries them, otherwise summarized (errors kept). Older conversation summarized, not dropped. |
| Attachments | All document types in v1. |

---

## 3. Process model and CLI

Three child processes supervised by the CLI:

1. **llama-server**: spawned with restart-tier settings. The CLI waits for its `/health` before starting the API.
2. **FastAPI backend**: owns the DB, run executor, event streaming.
3. **Client dev/static server**.

CLI responsibilities:
- Read `settings.json`, validate, spawn, prefix and stream logs.
- Write `launched.json` (the restart-tier values llama-server was actually started with, plus a `launch_id`). The backend compares it to `settings.json` to show a "restart required" badge.
- On exit or force-quit, kill the whole process group (Windows: job object). Test early that no orphaned llama-server keeps VRAM.

---

## 4. Settings

`settings.json` keys carry an apply-time tag.

| Key | Tier |
|---|---|
| model path / name, context size, GPU layers, llama-server and API ports, `supports_thinking`, `supports_vision` | restart |
| top_p, top_k, temperature, system prompt, default `thinking`, context-pruning threshold, attachment inline-size limit, max tool iterations | live |

Rules:
- A run **snapshots** the resolved live settings at creation (`runs.settings_snapshot`) and records the `launch_id`. Editing settings mid-run affects only the next run.
- Per-message options are validated against an allowlist (`thinking` only). Unknown keys return 422.
- UI edits to restart-tier keys write the file and show "restart required".

---

## 5. Data model (SQLite)

Conventions: ULID primary keys, integer epoch-millisecond timestamps, JSON stored as TEXT.

### chats
`id`, `title` (nullable), `root_id` (FK nodes), `created_at`, `updated_at`, `deleted_at`.

### nodes (the tree)
| Column | Notes |
|---|---|
| id | PK |
| chat_id | FK |
| parent_id | FK nodes; null only for root |
| role | `root`, `user`, `assistant` |
| content | user: JSON blocks (text, attachment refs). assistant: null (content lives in `steps`) |
| run_id | assistant only; FK runs; unique |
| selected_child_id | FK nodes; which child the UI currently shows |
| created_at | sibling order for `< >` |

- Every chat has a synthetic `root` node so the first message always has a parent and editing it is an ordinary sibling operation.
- Visible path = root, then follow `selected_child_id` to the leaf.
- Switching versions = update one parent's `selected_child_id`. No inference.
- A new user message may attach only to root or to an assistant node whose run is `completed`.
- The assistant node is created at run start, so siblings appear live and failed/cancelled runs remain visible.
- The system prompt is not in the tree; it comes from the settings snapshot.

### steps (durable record inside an assistant node)
`id`, `node_id`, `idx`, `kind` (`thinking` | `text` | `tool_call` | `tool_result`), `content` (JSON), `call_id`, `is_error`, `status` (`complete` | `partial`), `tokens`.

The context builder reads only `steps`, never events, and skips `thinking` steps.

### runs
| Column | Notes |
|---|---|
| id | the run id |
| chat_id, user_node_id, assistant_node_id | FKs |
| origin | `send` / `retry` / `edit` (analytics only) |
| status | `running`, `cancelling`, `completed`, `failed`, `cancelled`, `interrupted` |
| options | JSON per-message toggles |
| settings_snapshot | JSON resolved live settings |
| launch_id | which llama-server launch it ran against |
| error | JSON: code, message, phase |
| usage, context_stats | JSON |
| last_seq | highest event seq written |
| started_at, finished_at | |

**Global lock in the database:** a partial unique index over a constant expression for rows with status `running` or `cancelling`. A second concurrent start fails the constraint and is translated to 409, even under a race.

### run_events
PK (`run_id`, `seq`); `ts`, `type`, `payload`. Append-only replay log.

### Attachments
- `attachments`: id, sha256, original_name, mime, size, storage_path, created_at (deduped by hash).
- `node_attachments`: node_id, attachment_id, position. On edit, copied to the new user node unless the user removed one.
- `attachment_extractions`: attachment_id, extractor_version, status, text_path, token_count, page_count, mode (`inline` | `handle`), error. Unique on (attachment_id, extractor_version).

### context_summaries (pruner cache)
`id`, `scope` (`tool_result` | `history`), `target_id` (step id, or last covered node id), `parent_summary_id`, `text`, `tokens`, `source_hash`, `created_at`.
A history summary "through node X" is valid for every path through X and extends the previous summary. Edits create new nodes, so stale summaries are unreachable from new branches.

---

## 6. Tree operations

| Operation | Effect |
|---|---|
| Send | New user node under the current leaf (completed assistant node or root) + new assistant node + run |
| Edit | New user node as a sibling of the edited one (same parent), copied attachments, new run |
| Retry | New assistant node as a sibling of the existing one (same user node), new run from step 0 |
| Select | Set a parent's `selected_child_id`; no run |

All start operations go through one "start run" path guarded by the global lock.
A cancelled run with partial output is kept as an assistant node (`status=cancelled`) so it can be retried or compared; it cannot be a parent for new messages in v1.

---

## 7. Run lifecycle

1. `POST` start (send / edit / retry) validates, creates nodes and the run row (snapshot, `launch_id`), returns `run_id`. DB constraint enforces one active run.
2. Executor (asyncio task) emits `run_started`, builds context, builds a **fresh Strands agent**, streams, writes events and steps.
3. Frontend subscribes via SSE with replay. Disconnects never affect the run.
4. Completion writes final status, assistant-node finalization and the terminal event in **one transaction**.
5. `POST /runs/{id}/cancel` is the only way to stop a run (see section 9).
6. On backend startup: runs still `running`/`cancelling` become `interrupted`.

Process model: an asyncio task inside FastAPI is enough to survive frontend death. A separate worker process only adds survival of API restarts and can be introduced later behind the same executor interface.

---

## 8. Event contract

Envelope: `run_id`, `seq`, `ts`, `type`, `data`, `agent` (defaults to `main`; reserved for sub-agents).

| Type | `data` |
|---|---|
| `run_started` | chat_id, user_node_id, assistant_node_id, origin, options, settings_snapshot |
| `context_built` | tokens_before, tokens_after, budget, pruned{tool_calls_removed, tool_results_dropped, tool_results_summarized, history_summarized}, attachments[{id, mode}] |
| `context_summarizing` | target, status (`started` / `finished`) |
| `thinking_delta` | step_id, text |
| `text_delta` | step_id, text |
| `tool_call_started` | step_id, call_id, name, arguments |
| `tool_call_finished` | step_id, call_id, status (`ok` / `error` / `cancelled`), is_error, result_preview, result_truncated, duration_ms |
| `step_finished` | step_id, kind, status, tokens |
| `usage` | prompt_tokens, completion_tokens, iteration |
| `warning` | code, message |
| `cancel_requested` | none |
| `run_completed` | finish_reason, usage_total, duration_ms |
| `run_failed` | error{code, message, retryable}, phase |
| `run_cancelled` | phase, partial (bool) |

Rules:
1. Exactly one terminal event per run; the stream closes after it. Terminal event, run status and node finalization are one transaction.
2. `seq` is gap-free and monotonic per run, starting at 1.
3. Deltas are coalesced server-side (~50 ms or N chars) before being written.
4. Replay: SSE `id` = `seq`. On reconnect, subscribe to live first, then read missed rows from the DB, then dedupe by seq.
5. In-progress steps exist only in events. The `steps` row is written at `step_finished`. On cancel/failure, partial steps are finalized from accumulated deltas with `status=partial`.
6. Error codes are stable (`llama_unreachable`, `context_overflow`, `tool_failed`, `cancelled`, `internal`, ...). The UI never parses messages.
7. Namespace `verification_*` is reserved for the future verification gate.

---

## 9. Strands translation layer

### Components
- **ContextBuilder**: DB path -> pruned Strands messages (pure function plus summary-cache reads).
- **RunExecutor**: owns one run: builds the agent, drives the stream, handles cancel and failure.
- **EventSink**: the only writer of `run_events`; assigns `seq`; coalesces deltas; broadcasts to live subscribers.

Strands is **stateless per run**: fresh `Agent` each run, `messages` set from the built context, no Strands session manager. The DB is the source of truth.

### Model adapter
Use the built-in `LlamaCppModel` (`strands.models.llamacpp`), pointed at the local llama-server. Sampling parameters (`top_k`, `top_p`, `temperature`, etc.) go through its `params`; it also supports llama.cpp-specific options such as `cache_prompt`, and it maps context overflow to `ContextWindowOverflowException`. Multimodal input requires llama-server started with `--mmproj`.

### Mapping output to events
Two sources, two jobs:

| Source | Used for |
|---|---|
| `agent.stream_async(...)` events (text deltas, reasoning events with `reasoningText`, tool events) | live preview: `text_delta`, `thinking_delta` |
| Hook events (before/after invocation, model call, tool call, message added) | structural truth: step rows, `tool_call_*`, `step_finished`, `usage` |

Steps are built from **complete messages**, not reassembled deltas. Each content block of an assistant message becomes one `steps` row; the following tool-result message becomes `tool_result` steps. `step_id` is generated when the executor first sees a block so deltas and `step_finished` share it.

Hooks are bundled into one plugin/hook-provider ("RunEvents") constructed per run with the sink. Strands supports both the `HookProvider` protocol and a `Plugin` class with `@hook` methods; hook callbacks may be async, and ordering can be set with `HookOrder`. Per-run context can also be passed through `invocation_state`.

Hooks used from day one:
- Before tool call: emit `tool_call_started`; check cancel; the hook can also veto a call (`cancel_tool`), which is where the verification gate will live.
- After tool call: emit `tool_call_finished`; `exception` and `result.status` give a reliable `is_error`; apply preview truncation and result-persistence policy. `retry` is available for transient tool failures.
- Before/after model call: usage and timing. After-model-call has `exception` and `retry`, usable for transient llama-server failures.

### Execution limits
Use Strands' native per-invocation `limits` (turn count, total tokens, output tokens) instead of a hand-rolled counter. Exhausted limits surface as stop reasons (for example `limit_turns`); map them to a `warning` plus `run_completed` with that `finish_reason`. Token limits are checked between turns, so a single model call can exceed the budget.

### Cancellation
`agent.cancel()` exists (thread-safe, idempotent, yields stop reason `cancelled`, signal clears when the invocation ends). It is cooperative and checked at checkpoints such as the top of each loop cycle.
Plan:
1. API sets run status `cancelling`, emits `cancel_requested`.
2. Executor calls `agent.cancel()` **and** cancels its asyncio task so the in-flight HTTP stream to llama-server is closed and the GPU is freed (spike S3 confirms how much each does).
3. Running tools get an optional `cancel()` (subprocess tools must be killed explicitly).
4. `finally`: finalize in-progress steps as `partial`, then write `cancelled` + `run_cancelled` atomically and release the lock.
Cancel during a tool call is the case most likely to leak; test it first.

### Failure
Same `finally` path with `run_failed` and a coded error. Exception-to-code mapping lives in one function. Backend crash: startup marks leftover active runs `interrupted` and finalizes empty assistant nodes.

---

## 10. Context builder and pruning

`build_context(path_nodes, settings_snapshot) -> messages`, rebuilt every run.

Reconstruction: each prior assistant node is replayed from `steps` as (assistant message with text + tool-use blocks) then (user message with tool results), per model-call round. `thinking` steps are never replayed.

Pruning policy (applies only to completed earlier turns; triggered when estimated tokens exceed a threshold, default about 70% of context size):
1. System prompt: never touched, always first.
2. Current turn: never pruned.
3. Older turns, in order:
   - strip tool calls;
   - tool results: drop only if the assistant reply carries the content (default: keep a summary; drop purely navigational results);
   - tool **errors**: keep a one-line summary so the model can see repeated failures and avoid loops;
   - older user/assistant exchanges: fold into a running summary rather than deleting.
4. **Tool calls and results stay paired.** When stripping, replace both with summary text inside the assistant message. Never leave an orphaned result.

Summaries are produced by the local model in a separate non-agent call, **cached** in `context_summaries` (keyed by node/step), so retries and branches pay nothing and the prompt prefix stays byte-stable. Stable prefixes matter because llama-server's prompt cache (`cache_prompt`) only helps when the beginning of the prompt is identical between requests; deterministic pruning and cached summaries preserve that. Token estimation can use llama-server's `/tokenize` endpoint for accuracy.

Attachments on the current message become content blocks or an excerpt plus a handle; older nodes keep the mode recorded at extraction time.

---

## 11. Attachments

Extraction runs at send time (not run time) and is cached by content hash and extractor version.
- Images: image block if `supports_vision`, otherwise skipped with a `warning`.
- PDF, docx, xlsx, csv, text and similar: extracted to text/structured summaries.
- Large documents: not inlined; excerpt plus handle, read through a document tool later. The inline-size limit is a live setting.

---

## 12. API surface

| Endpoint | Purpose |
|---|---|
| `POST /chats/{id}/messages` | send (text, attachments, options) -> `run_id` or 409 |
| `POST /nodes/{id}/edit` | edit user node -> `run_id` or 409 |
| `POST /nodes/{id}/retry` | retry (new assistant sibling) -> `run_id` or 409 |
| `POST /nodes/{id}/select` | switch version via `selected_child_id` |
| `GET /chats/{id}/tree` | visible path + sibling counts |
| `GET /runs/active` | the single active run, if any (frontend asks this first on reconnect) |
| `GET /runs/{id}` | status snapshot |
| `GET /runs/{id}/events?after=seq` | SSE with replay |
| `POST /runs/{id}/cancel` | cancel |
| `GET/PUT /settings` | read/write settings; reports restart-needed keys |

---

## 13. Strands spike (do before building the executor)

Version: assume the latest release; at the time of writing the newest changelog entry found was Python `strands-agents` 1.55.0 (2026-09-08). Repository is now `strands-agents/harness-sdk`. Pin the version you install and re-run the spike on upgrades.

**Already confirmed from the docs**
- `stream_async` yields text, tool, lifecycle and reasoning events (`reasoning`, `reasoningText`) and a final `result`.
- Hook events: before/after invocation, before/after model call (with `exception`, `retry`), before/after tool call (`cancel_tool`, `selected_tool`, `interrupt`, `exception`, `retry`). `HookProvider` and `Plugin`/`@hook` both supported; async callbacks allowed; `HookOrder` available.
- `agent.cancel()` exists and yields stop reason `cancelled`.
- Native per-invocation limits exist (turns, total tokens, output tokens).
- `LlamaCppModel` exists with `params` incl. `top_k`, `cache_prompt`; overflow mapped to `ContextWindowOverflowException`.

**Still to verify with a script (one agent, one tool, print every stream and hook event)**
- S1: whether `chat_template_kwargs: {enable_thinking: ...}` can be passed through `LlamaCppModel.params` (if not, subclass the model or patch the request body).
- S2: whether llama-server's reasoning arrives as a separate field that maps to Strands `reasoningText`, or inline in text (then split on think tags yourself). Depends on llama-server version and flags.
- S3: what `agent.cancel()` actually interrupts mid-generation versus task cancellation; confirm llama-server frees the slot when the connection closes.
- S4: exact name and timing of the message-added hook, and whether it fires for tool-result messages.
- S5: shape of tool errors (`result.status`, `exception`) to set `is_error` reliably.
- S6: where token usage comes from per model call.
- S7: `Agent(messages=...)` accepts the reconstructed history including tool-use/tool-result pairs for your model's chat template.
- S8: dependency compatibility: install into a clean venv with FastAPI, uvicorn, pydantic, httpx, SQLAlchemy/aiosqlite (or your DB layer) and confirm the resolver is happy; check the package's required Python version on PyPI. Use `uv` or `pip install --dry-run` and commit the lockfile.

The spike script doubles as the fixture for executor tests.

---

## 14. Roadmap after the basic pipeline

1. Tools with hooks (per-run limits, result truncation, verification gate via `cancel_tool` and the `verification_*` event namespace).
2. Sub-agents as child runs (`parent_run_id`, `agent` field in the envelope, same event log).
3. Automations: scheduler that creates runs without a frontend (supported by the design as is).
4. Optional: separate worker process, event compaction after terminal state, checkpoint/resume (explicitly out of scope today).

## 15. Open questions
- Should a cancelled partial answer ever be usable as a parent for new messages? (Currently no.)
- Event retention: keep everything for v1; compact deltas after a run is terminal later?
- Whether the `thinking` toggle should be disabled automatically when `supports_thinking` is false, or hidden.
