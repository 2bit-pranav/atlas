# Atlas on Strands: Architecture, Tool Ecosystem and Skills

Status: design agreed through 2026-10-11. Built: L0, L1, L2, L3, L4a/4b (tabular and text ingestion), L5. Next: L4c (Docling `standard`, rich documents). Deferred on purpose: L0b and the tool-call guard until L6 is built (see the L0b note in section 19). Scope: backend chat pipeline, run engine, ingestion, tool ecosystem, skills, context management. Frontend rebuild comes later.
Still open (do not block the base): persistent-library RAG and factual memory (section 17).
Next step: L4c (Docling `standard`; answer S15 on real documents first), then L6 (context management), then L0b and the tool-call guard (section 9.1), then L7. Spike items are attached to the layer where they matter (section 16).

Layer status (2026-10-11): L0 done, L1 done, L2 done, L3 done, L4a/L4b done, L4c next, L4d/L4e pending, L5 done, **L0b deferred until after L6**, L6-L8 pending. Test and spike scripts were run and reported in this document but are kept out of the repository; the answers in section 16 are the record.

Changes in the 2026-10-10 version:
- **L0 answers recorded (section 16):** S1, S2, S6, S7, S8 answered. The model adapter is our own thin subclass of `LlamaCppModel` (section 9, Model adapter), not the stock class.
- **Tool-call guard designed (section 9.1):** protection against the two failures seen in the AutoGen version (tool call leaked into `content`; empty tool result). Principle: prevent first, detect always, repair only what measurement shows is needed, and never grow into the old `config.py`. New layer **L0b** measures real failure rates before any parser is written; a slim guard ships with L3.
- **Old `config.py` reviewed** as a source of fixtures and patterns only (section 9.1.6). Nothing is ported.
- **llama-server slots (L1, section 19):** the launch uses 4 slots with a 32k context; per-slot context must be verified, and Atlas should pin one slot per run.
- **Build pinning (L1, section 19):** llama.cpp build and GGUF hash go into `launched.json`; tool-call behaviour depends on both.
- **Cloud models (section 9, Model adapter):** the guard is local-only by default; cloud models use their stock clients.
- **Spikes S21-S26 added (section 16).**

Changes since the 2026-10-08 version:
- **Skills now use Strands' built-in `AgentSkills` plugin** (section 11.5). It provides the SKILL.md format, the catalog in the system prompt and the `skills(skill_name=...)` activation tool, but it does *not* bundle tools. So our skill tools are registered up front, and a before-tool-call hook gates them until the skill has been activated. The dynamic tool-activation mechanisms (A/B/C), the `load_skill` tool and LRU eviction are removed; they remain only as a scaling escape hatch.
- **Granite-Docling (VLM) is an optional second Docling pipeline** (section 12): `standard` pipeline by default for born-digital documents, `vlm` for scanned/hard pages, served by a local llama.cpp server on CPU. The default is decided by spike S15 on real documents.
- **Thinking:** passed per request through llama.cpp's extra request arguments (per the Unsloth llama.cpp notes); S1 is reduced to a confirmation.
- **Section 19 rewritten** as a layer-by-layer build sequence with interfaces, tests and spikes per layer; section 16 spikes are now assigned to layers.

Changes in the 2026-10-08 version:
- **Ingestion generalized (sections 11.3, 11.4, 12):** Docling is the parser for all document types; spreadsheets/CSV use a direct tabular reader; every parser returns the same `IngestResult` contract. Summaries are generated lazily.
- **Storage routing rule (11.3):** decided by the *kind* of output an ingestor produces, never by guessing content. Tables -> DuckDB, text/outline/vectors -> SQLite, ambiguous tables stored in both.
- **Retrieval index (5, 11.4):** new `chunks` table with FTS5 and vectors; `search` is hybrid (keyword + vector) once vectors exist.
- **Skills spec (11.5) rewritten in full:** package format, tool and error contracts, lifecycle, activation fallbacks, trust model, testing, v1 skill set.
- **Draft SDK (11.6):** `doc_drafts` generalized to `drafts` (kind = docx, pptx, ...); event `doc_rendered` renamed `draft_rendered`.
- **API (14):** attachment status endpoint; sending with an unfinished attachment is rejected.
- **Spikes S15-S19 added (16); build order added (19).**

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
- Runtime model swapping, token-budget thinking control, run queueing, mid-run checkpoint/resume, multi-user, model-authored skills.

---

## 2. Decisions log

| Topic | Decision |
|---|---|
| Launch | One CLI starts client, FastAPI and llama-server from `settings.json`. Force-quitting the CLI kills all. |
| Model | One model, fixed at launch. No swapping. |
| Thinking | Boolean `thinking`, not token budgets. Hidden if the model has no thinking support. Sent per request as an extra argument (`chat_template_kwargs.enable_thinking`), so toggling needs no restart. |
| Settings | `settings.json` is the single source of truth. Per-message input exposes only toggles (currently `thinking`). |
| Setting tiers | **Restart-needed**: model, context size, GPU layers, ports, embedding model. **Live**: top_p, top_k, temperature, system prompt, thinking default. Live settings apply from the next run. |
| App state and text index | SQLite (WAL, foreign keys on): app state, chunks, FTS5, vectors. |
| Data store | **DuckDB**, one file per chat, for tables and analysis. |
| **Storage routing** | By the *kind of output* an ingestor/tool produces: tables -> DuckDB; text, outline, vectors, app state -> SQLite. Ambiguous tables are stored in both. The model never chooses a store; it chooses a tool. |
| **Parsing** | **Docling** for all document types (PDF, DOCX, PPTX, HTML, images, markdown). Spreadsheets/CSV use a direct tabular reader. One shared `IngestResult` contract. For PDFs/images two pipelines sit behind one setting: `standard` (layout + table models, copies the embedded text layer) and `vlm` (Granite-Docling 258M served locally). |
| **Retrieval** | Hybrid: FTS5 keyword + vector similarity on CPU embeddings; keyword-only until vectors are ready. |
| **Summaries** | Outline and token counts are free at ingest; document/section summaries are generated lazily on first need and cached. |
| Concurrency | One active run globally. No queue. 409 on a second start. Send button disabled while a run is active. Ingestion runs in a separate single worker and is independent of the run lock. |
| Branching | Message tree. Edit = sibling user node. Retry = sibling assistant node (new run). |
| Retry | Restarts from step 0. No checkpoints. Interrupted/failed/cancelled runs are recovered by retrying. |
| Cancel | Required in v1. |
| Extension mechanism | **Skills**, using Strands' built-in `AgentSkills` plugin for the SKILL.md format, the catalog and activation. Our tools live beside the skill (`tools.py`), are registered up front and are gated until the skill is activated. Document capabilities (docx now, pptx later) are skills. The model does not know whether a capability is built-in. |
| Always-on tools | Only universal basics: file/data access, notepad, and the built-in `skills` tool. |
| Charts | Rendered as images (PNG) in v1. |
| Data passing | **By reference.** The model never retypes bulk data; tools take result ids or SQL. |
| Context window | 32k. Budget split in section 10. |
| Attachments | All document types in v1. |

---

## 3. Process model and CLI

Three child processes supervised by the CLI, plus one optional on-demand ingest server:

1. **llama-server**: spawned with restart-tier settings; the CLI waits for `/health`.
2. **FastAPI backend**: owns SQLite, DuckDB files, the run executor, event streaming, and the ingest worker (a separate process pool of size 1 inside the backend, so Docling never blocks the event loop).
3. **Client dev/static server**.
4. **Ingest VLM server (optional, on demand)**: a second llama-server serving Granite-Docling (GGUF + its projector file), started by the ingest worker only when a document needs the `vlm` pipeline and stopped after an idle timeout. CPU by default (`ingest.vlm.gpu_layers = 0`) so Gemma keeps the VRAM. It is a child of the same process group, so force-quit still cleans it up.

CLI responsibilities:
- Read and validate `settings.json`, spawn, prefix and stream logs.
- Write `launched.json` (restart-tier values actually used + a `launch_id`). The backend compares it to `settings.json` to show "restart required".
- On exit/force-quit, kill the whole process group (Windows: job object). Test early that no orphaned llama-server keeps VRAM.

Per-chat workspace on disk: `workspace/<chat_id>/{data.duckdb, uploads/, scratch/, outputs/}`.

---

## 4. Settings

| Key | Tier |
|---|---|
| model path/name, context size, GPU layers, ports, `supports_thinking`, `supports_vision`, `embedding.model`, `embedding.enabled`, `ingest.vlm.model_path`, `ingest.vlm.gpu_layers` | restart |
| top_p, top_k, temperature, system prompt, default `thinking`, pruning thresholds, per-result token cap, display budget, max tool iterations, `skills.dirs`, `skills.pinned_token_cap` (default 2000), `ingest.device` (default cpu), `ingest.docling.pipeline` (standard / vlm / auto; default decided by spike S15) | live |

- A run **snapshots** resolved live settings (`runs.settings_snapshot`) and records the `launch_id`.
- Per-message options are validated against an allowlist (`thinking` only). Unknown keys return 422.
- UI edits to restart-tier keys write the file and show "restart required". Changing `embedding.model` also requires re-embedding (vectors record the model id; mismatches are detected and re-queued).

---

## 5. Data model (SQLite, app state and text index)

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

### Attachments and ingestion
- `attachments`: id, sha256, original_name, mime, size, storage_path, handle, created_at (deduped by hash).
- `node_attachments`: node_id, attachment_id, position. Copied to the new user node on edit unless removed.
- `attachment_extractions`: attachment_id, `parser` (`docling` | `tabular` | `text`), `parser_version`, `docling_pipeline` (`standard` | `vlm` | null), `status` (`queued` | `running` | `ready` | `failed`), `progress` (0-1), `embed_status` (`none` | `pending` | `ready` | `failed`), `embed_model`, `outline` (JSON), `table_ids` (JSON), `warnings` (JSON), `token_count`, `page_count`, `doc_json_path` (the saved Docling document, so re-chunking never re-parses), `error`. Unique on (attachment_id, parser, parser_version, docling_pipeline).
- `chunks`: id, attachment_id, extraction_id, `scope` (`chat`; `library` reserved for later), idx, `kind` (`text` | `table_text` | `schema` | `caption`), `section_path`, `location` (JSON: page, heading path), `text`, `tokens`.
  - FTS5 virtual table `chunks_fts(text, section_path)` over `chunks`.
  - Vector table `chunk_vectors(chunk_id, embedding)`: `sqlite-vec` virtual table, with a fallback of BLOB + brute-force cosine in numpy (fine for tens of thousands of chunks). Spike S16.
- `attachment_summaries`: attachment_id, `section_path` (null = whole document), `text`, `tokens`, `model_id`, `created_at`. Filled lazily (section 12).

### Catalog and objects
- `catalog_objects`: id, chat_id, run_id, step_id, node_id, name, kind (`table` | `text` | `file` | `draft` | `image`), `store` (`duckdb` | `sqlite` | `disk`), schema (JSON), row_count, tokens, provenance (the SQL/tool call that produced it), created_at.
- `text_objects`: object_id, body, plus an **FTS5** index over it (text tool results).
- Objects are **immutable**: nothing is edited in place; a derived object is created instead. Every number therefore has recorded lineage.
- **Branch visibility:** tools resolve an object id only if it is an attachment of the current chat or was created by a node on the current path.

### scratch_state
`run_id`, `plan` (JSON), `notes` (JSON), `active_skills` (JSON list of skill names activated in this run; restored into the fresh agent at the start of the next run), `version`. Rendered into the pinned notepad block. Compacted to `nodes.task_state` at run end.

### drafts
`id`, `chat_id`, `kind` (`docx` | `pptx` | ...), `name`, `spec` (JSON block list with server-assigned block ids), `version`, `rendered_path`, `created_at`, `updated_at`. (Generalizes the earlier `doc_drafts`; see the Draft SDK in 11.6.)

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

All start operations go through one "start run" path guarded by the global lock. Attachments are checked for existence only: a send is **never** rejected for a file that is still parsing (see the L0b interlude in section 19 -- the wait moved inside the run, where it delays the first token rather than the user). A cancelled run with partial output is kept as an assistant node (`status=cancelled`) so it can be retried; it cannot be a parent for new messages in v1.

---

## 7. Run lifecycle

**Attach (before send):** upload endpoint stores the file, hashes it, creates the attachment with status `queued` and returns its handle (`f1`) immediately. The ingest worker processes it (section 12); the UI polls the status and shows progress on the chip.

**Send:**
1. `POST` start validates, creates user node, assistant node and run row (snapshot, `launch_id`), returns `run_id`. The DB constraint enforces one active run.
2. Executor (asyncio task) emits `run_started`, restores `active_skills` from the previous `task_state`, builds context, builds a **fresh Strands agent**, streams, writes events and steps.
3. Frontend subscribes via SSE with replay. Disconnects never affect the run.
4. Completion writes final status, node finalization, compacted `task_state` and the terminal event in **one transaction**.
5. `POST /runs/{id}/cancel` is the only way to stop a run (section 9).
6. On backend startup, runs still `running`/`cancelling` become `interrupted`; ingest jobs still `running` are re-queued.

Process model: an asyncio task inside FastAPI is enough to survive frontend death. A separate worker process for runs can come later behind the same executor interface.

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
| `skill_loaded` | name, tools[], body_tokens (emitted by a hook when the built-in `skills` tool is called) |
| `object_created` | id, kind, name, rows?, tokens, source_step |
| `scratch_updated` | plan, notes, version |
| `draft_rendered` | draft, kind, path, attachment_id, checks[{name, status, detail}] |
| `usage` | prompt_tokens, completion_tokens, iteration |
| `guard_event` | kind (`leak_suspect`/`empty_response`/`empty_tool_result`), action (`retry`/`extract`/`nudge`/`fail`), tool?, raw_excerpt, attempt (section 9.1) |
| `warning` | code, message (codes include `tool_call_recovered`, `attachment_skipped`, `limit_turns`, `skill_stubbed`) |
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

Ingestion is outside any run, so it has no event stream in v1; the UI polls `GET /attachments/{id}`.

---

## 9. Strands translation layer

### Components
- **ContextBuilder**: DB path -> pruned Strands messages (pure function + cache reads).
- **RunExecutor**: owns one run: builds the agent, drives the stream, handles cancel and failure.
- **EventSink**: only writer of `run_events`; assigns `seq`; coalesces deltas; broadcasts.
- **ToolRuntime**: tool registry (core + skill tools), `AgentSkills` wiring and the skill gate, result offloader, argument validator.

Strands is **stateless per run**: a fresh `Agent` each run, `messages` from the built context, no Strands session manager. The DB is the source of truth.

### Model adapter
`AtlasLlamaCppModel` (`atlas/models/llamacpp_atlas.py`): a small subclass of Strands' `LlamaCppModel`, kept in one file so it can be deleted when upstream catches up. It exists because of two L0 findings: (1) the stock class silently drops `chat_template_kwargs` (needed for `enable_thinking`, which must be sent explicitly on every request because the server default is thinking ON); (2) the stock `stream()` ignores `delta.reasoning_content`. The subclass also hosts the tool-call guard (section 9.1). Sampling params (`top_k`, `top_p`, `temperature`, ...) go through `params`; it also supports `cache_prompt` and maps context overflow to `ContextWindowOverflowException`. Multimodal requires llama-server started with `--mmproj`.

### Mapping output to events
| Source | Used for |
|---|---|
| `agent.stream_async(...)` events (text, reasoning via `reasoningText`, tool events) | live preview: `text_delta`, `thinking_delta` |
| Hook events (before/after invocation, model call, tool call, message added) | structural truth: steps, `tool_call_*`, `step_finished`, `usage` |

Steps are built from **complete messages**, not reassembled deltas. Hooks are bundled into one plugin/hook-provider ("RunEvents") per run. Strands supports `HookProvider` and `Plugin`/`@hook`; callbacks may be async; ordering via `HookOrder`; per-run context via `invocation_state`.

### 9.1 Tool-call guard (Gemma and llama.cpp reliability)

**Why it is needed.** Two failures were seen in the AutoGen version: (1) the model's tool call was written into the text (`content`) instead of the tool-call field; the harness took it as a final answer and the run ended silently; (2) a tool call ran but its result was empty and the harness crashed. Checked against Strands (1.58.0): neither is handled. A leaked call becomes plain text and the run ends as "finished"; a tool message with empty content is dropped when the request is built, which leaves a tool call with no result. Hooks cannot edit the model's response, so any repair belongs in the adapter we own, not in hooks.

**Principle.** Prevent, normalize, recover, contain, observe, in that order. Do not write a parser until measurement says one is needed.

**9.1.1 Prevent (cheap, always on)**
- Always send `tools` when tools are registered (a missing `tools` field means the server's parser never activates and calls leak as text).
- **Never start llama-server with `--tools all`.** That flag is llama.cpp's *own* agent toolkit (`read_file`, `write_file`, `exec_shell_command`, `get_info`, ...), not tool-call parsing; `--help` marks it experimental and "do not enable in untrusted environments". Atlas registers its own tools through Strands and keeps raw paths away from the model, so enabling it would hand the model a shell for no benefit. The local launch skeleton in the sibling repo carries it; drop it. (Found while building L1.)
- Keep tool schemas small and flat; at most ~12 tools visible; short names, simple argument types.
- Pin the llama.cpp build and GGUF hash in `launched.json`; re-run L0b on any change (parser and template bugs are fixed and introduced between builds).
- Do not let reasoning eat the output limit: leave headroom in `max_tokens` when thinking is on.
- Never replay a malformed turn into history (see 9.1.4).

**9.1.2 Empty results (fix at the source, deterministic)**
- A tool result is never empty. In the tool runtime (L5) and again in the adapter's request formatter, an empty or whitespace-only result becomes `"(no output)"` with the tool's status preserved. This removes failure 2 completely and needs no model cooperation.
- The same rule applies to a tool error with an empty message (use the exception type).

**9.1.3 Detect leaked calls (in the adapter, after a model response)**
A response is a **suspect** when it has no structured tool call AND the text matches any marker: `<|tool_call`, `<tool_call`, `tool_call|>`, `call:<known tool name>{`, `<|channel`, `<channel|>`, `<think>` outside the reasoning field, or the text is empty with no tool call. The tool-name rule only counts names that exist in the registered tool list, which avoids the bare `call:` false positives the old regex had. A suspect is never treated as a final answer.

**9.1.4 Recover (in this order, stop at the first success)**
1. **Retry the model call** (up to 2 times) with the suspect output discarded, so it never enters history. Retry is cheap on this hardware and fixes most sampling flukes. Optionally lower temperature on the retry.
2. **Extract** (only if L0b shows retries are not enough): parse the leaked call with one schema-validated extractor. A call is accepted only if the tool name is registered AND the arguments validate against that tool's schema. Otherwise it is rejected, not guessed. Accepted calls get a fresh `toolUseId` and are emitted as a normal tool-use. The leaked text is removed from what the user sees.
3. **Nudge**: append one short system-style note ("your last reply was not a valid tool call; call the tool again using the tool-call interface") and retry once.
4. **Fail loudly**: end the run as `run_failed` with code `tool_call_malformed`, keep the raw text in the step for debugging. A silent stop is never an outcome.

**9.1.5 Contain and observe**
- Every suspect, retry, extraction and failure is logged as a `guard_event` (new event type in section 8; fields: `kind`, `action`, `tool`, `raw_excerpt`, `attempt`) and counted per run and per model build.
- Reasoning text is split out of `content` in the adapter (`reasoning_content` field, plus inline `<think>` / `<|channel>thought...<channel|>` as a fallback) so thinking never reaches the user text or the history as content.
- Stray template tags are stripped from user-visible text only after the above.

**9.1.6 Lessons taken from the old `config.py` (patterns, not code)**
- Formats seen in the wild: `<|tool_call>call:Name{key:<|"|>value<|"|>}<tool_call|>`, the same without the wrapper (`call:name{...}`), inline `<think>` blocks, `<|channel>thought...<channel|>`, stray `tool_call` / `tool_response` / `channel` tags, and empty responses. These become **test fixtures** for the guard and the extractor, not production regexes.
- What not to repeat: regex-first repair of every response; guessing argument values by key/value regex; placeholder text such as `"[Empty response generated by model]"` standing in for a real error; thinking handled by a numeric budget (now a boolean).
- Slot pinning (`id_slot = hash(chat_id) % 8`) is kept as an idea but changed: see L1 (slots split the context).
- The "cloud model signature fix" in `config.py` (`create`/`create_stream` signatures and merging default extra args) was specific to AutoGen's client classes and has no counterpart in Strands, where cloud models use the stock model classes (Strands' own Anthropic/OpenAI/Bedrock providers). No cloud interceptor existed in the old code.

**9.1.7 Conditional parser rule.** Build the extractor (9.1.4 step 2) only if L0b measures more than ~2% of tool-calling turns still failing after two retries. Time-box it to one day, fixtures first. If failures stay above ~5% after that, switch to **Plan B**: a constrained action protocol, where each step the model must emit JSON matching a schema (`{"action": "call_tool"|"answer", ...}`) enforced by llama.cpp grammar / `json_schema`, and the adapter converts it into tool-use events itself. This removes the leak by construction at the cost of one more adapter.

**9.1.8 Where each piece lives**
- Adapter (`atlas/models/llamacpp_atlas.py`): suspect detection, retry loop, extractor (if built), reasoning split, empty-content normalization on request.
- Tool runtime (L5): never-empty results, `ToolError` messages.
- Run executor (L3): maps `tool_call_malformed` to `run_failed`, emits `guard_event`.
- Tests: fixtures from 9.1.6 through a `FakeModel` that emits leaked text, so the guard is tested without a GPU.

### Hooks (day one)
- **Before tool call**: emit `tool_call_started`; validate arguments (existence of ids/columns, size cap); **skill gate**: if the tool belongs to a skill (listed in its `allowed-tools`) that is not activated in this run, veto it with `error[not_loaded]: skill "X" is not activated; call skills(skill_name="X") first`; check cancel; can veto a call (`cancel_tool`) — the verification gate will live here.
- **After tool call (ResultOffloader)**: modifies the result before the model sees it (supported by Strands). Small results pass through; larger results are written to the data store and replaced by a preview + id (section 10). Also emits `tool_call_finished`, sets `is_error` from `result.status`/`exception`. `retry` is available for transient tool failures.
- **Before/after model call**: usage, timing, injecting the notepad block (needs spike S10), loop detection. After-model-call `retry` can absorb transient llama-server failures.
- **Loop detector**: identical call repeated, or the same error twice, injects a short nudge ("same call as before; try a different approach") and records a one-line error summary.
- **Skill state hooks**: before invocation, write the previous run's `active_skills` into the fresh agent's skill state (the `AgentSkills` plugin keeps activation in `agent.state`; spike S9); after a call to the `skills` tool, emit `skill_loaded`, record the skill in `scratch_state.active_skills`, and mark the result as pinned for the ContextBuilder.

### Execution limits
Use Strands' native per-invocation `limits` (turns, total tokens, output tokens). Exhausted limits surface as stop reasons (e.g. `limit_turns`); map them to a `warning` plus `run_completed` with that `finish_reason`. Token limits are checked between turns.

### Cancellation
`agent.cancel()` exists (thread-safe, idempotent, stop reason `cancelled`, checked at checkpoints such as the top of each loop cycle).
1. API sets run status `cancelling`, emits `cancel_requested`.
2. Executor calls `agent.cancel()` **and** cancels its asyncio task so the in-flight HTTP stream to llama-server is closed (spike S3 confirms what each does).
3. Running tools see `ctx.cancel_token` set; subprocess tools are killed explicitly; renders write to a temp file and rename atomically.
4. `finally`: finalize in-progress steps as `partial`, write `cancelled` + `run_cancelled` atomically, release the lock.
Cancel during a tool call is the case most likely to leak; test it first.

### Failure
Same `finally` path with `run_failed` and a coded error; mapping from exceptions to codes lives in one function. Backend crash: startup marks leftover active runs `interrupted` and finalizes empty assistant nodes.

---

## 10. Context management

### Principle: control plane vs data plane
The model works on the **control plane**: short commands, schemas, previews, notes and the prose it must write itself. All bulk data lives in the **data plane** (the chat's data store and text index), where deterministic code operates on it. Rows never pass through the model in either direction.

### Regions and budget (32k window; starting values, tune on real runs)
| Region | Tokens | Rule |
|---|---|---|
| Fixed: system prompt + tool definitions (core + skill tools) | ~4-5k | never pruned |
| Pinned: goal, notepad (plan + notes), loaded skill bodies | ~3k | never pruned during the task |
| Conversation history (older turns, summarized) | ~5k | summarized, cached |
| Rolling window of recent tool steps | ~10k | verbatim while recent |
| **Generation reserve** (thinking + answer) | ~8k | never spent on prompt |
| Headroom | ~2k | |

Thinking consumes the same window within a step, so the generation reserve is explicit.

Skill instructions arrive as the result of the built-in `skills` tool, so they are ordinary tool results that the offloader and demotion rules must **not** touch (pinned). Pinned skill bodies are capped at `skills.pinned_token_cap` (~2k tokens) in total; if the cap is exceeded the oldest body is replaced by a stub (`[skill X loaded earlier - call skills(skill_name="X") to re-read]`).

### Result offloading (pruning by construction)
Every tool result passes through the ResultOffloader:
- **<= ~400 tokens**: passes through unchanged.
- **Larger**: full body stored in the data store (table object in DuckDB, text object in SQLite), and the model receives a compact reply: preview (head/first rows), shape/size, id, and the next action, e.g. `[r7] 340 rows x 6 cols, 8.1k tokens. Preview: ... Use show(r7, ...) or query on r7.`
- **Per-result hard cap**: ~1.5k tokens of anything that is shown inline.
- **Query results are always saved** as objects (auto id `r1`, `r2`, or `save_as`) and only *displayed* if they fit the display budget (~400 tokens, TSV, with shape and a truncated flag). Saving is cheap, so the model never has to decide whether to save.

### Demotion inside the current turn
Nothing in the current turn is deleted, but results are **demoted**: once the rolling window is full, the oldest results are replaced in context by one-line stubs (`[r7: read f1 p1-3, 2.1k tokens - show(r7) to re-read]`). The model's own text and the user's prompt are never stubbed.
**Exception:** large authored arguments (e.g. a long `doc_text`) are replaced by a stub after the call succeeds (`[wrote 1.1k tokens to block b4 of d1]`), since the draft already holds the content. Needs spike S13; fallback is to keep arguments small by writing documents in sections of <= ~300 tokens.

### Pass by reference
- Tool arguments over ~800 tokens are rejected: "pass data by reference (result id or SQL), don't inline it."
- Tools that move data (`doc_table`, `doc_chart`, `export_table`) take `source` = result id or alias, never rows.

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
- `plan`: <= 12 items, each `pending | doing | done`.
- `notes`: <= 20 items, each short text + optional reference (`r3`, `f1 s2`). **Facts and decisions go in notes; data goes in tables.**
- Hard caps return errors ("notepad full 20/20, merge or remove a note"), not silent truncation. Rendered block <= ~1.5k tokens, pinned.
- At run end it is compacted into `nodes.task_state` (plan, notes, active skills) and pinned again in the next run of that chat, so follow-ups continue instead of restarting.

---

## 11. Tool ecosystem

### 11.1 Principles
1. Small uniform surface: always-on core of 11 tools, consistent argument names and result shapes.
2. **Handles, not paths.** Files are `f1`, results `r7`, drafts `d1`. The model never types a filename.
3. **Validate, then teach.** Check arguments against schemas and real state; errors list valid options (`sheet "Q5" not found; available: Q1..Q4`).
4. Results are context spend: every tool has a result budget, compact formats (TSV), and pagination with cursors.
5. Reads are always safe and cacheable; writes go to a versioned workspace and are where verification attaches.
6. Capability grows by adding skills, not by growing the always-on tool list.
7. Skill tools are visible from the start (constant tool definitions keep the prompt prefix cacheable); the `skills` tool plus a gate make the model read a skill's instructions before using its tools.

### 11.2 Core (always-on) tools
| Tool | Purpose |
|---|---|
| `list_files()` | attachments and outputs of this chat |
| `outline(handle)` | structure: pages, headings, sheets with row counts, token counts per section |
| `read(handle, section / pages / chunk / cursor)` | structure-aware read, ~1k tokens per page by default; `chunk` reads around a search hit |
| `search(target, query)` | `target` = a file handle, a text object id, or `all` (every attachment in this chat). Hybrid keyword + vector search when vectors are ready, keyword-only otherwise (the mode is not exposed to the model). Returns the top 5 snippets (<= ~80 tokens each) with location and chunk id |
| `describe(id)` | schema, 5 sample rows, stats, data-quality warnings for tables; summary for files/drafts |
| `query(sql, save_as?)` | read-only SQL over all tables; result always saved; displayed only if small |
| `show(id, rows/cols/offset or range/cursor)` | paginated view of any stored object |
| `collect(table, rows)` | append a few structured rows (extracted from prose) to a named collector table; first call fixes the schema |
| `plan(items)`, `note(text, ref?)` | notepad |
| `skills(skill_name)` | built-in tool of the Strands `AgentSkills` plugin: returns a skill's instructions and marks it activated (section 11.5) |

Which store a tool reads is fixed inside the tool: `outline`, `read`, `search` use the SQLite text index; `query`, `describe` (for tables) use DuckDB; `show` reads whatever store the object lives in (its catalog row says which).

### 11.3 Data store (DuckDB) and the routing rule

**Routing rule.** Where a piece of data is stored is decided by the *kind of output* the producing ingestor or tool declares, never by inspecting the content:

| Output kind | Store | Why |
|---|---|---|
| Tables (sheet, CSV, table found inside a document), query results, collector tables | DuckDB | data you compute over with SQL |
| Text chunks, outline, vectors, tool-result text | SQLite | search and lookup |
| Chats, runs, events, catalog, drafts, notepad | SQLite | app state |

**Ambiguous case:** a table inside a PDF/DOCX may be data or just layout. It is not classified. Every table Docling reports goes to DuckDB *and* its text rendering is added to `chunks` (kind `table_text`), so both SQL and keyword/vector search can find it.

Details:
- One DuckDB file per chat: `workspace/<chat_id>/data.duckdb`.
- Spreadsheets/CSVs become tables named `<handle>_<sheet>` (sanitized). Sheets with the same header signature are also exposed as one unified view `<handle>_all` with a `_sheet` column (`UNION ALL BY NAME`). Sheets that do not match are listed separately in `describe`.
- Tables found inside documents are registered as `<handle>_t<n>` (Docling table -> DataFrame -> DuckDB).
- Type inference and data-quality warnings are recorded at ingestion ("revenue has 2 non-numeric values in Mar").
- `query` runs on a **read-only connection** with a timeout and a cap on materialized rows.
- `collect` is how repeated facts from many prose documents become a table instead of loose notes.
- Data store contents are deleted with the chat.
- If files stay small, SQLite alone could do the same work; DuckDB is kept for direct xlsx/csv ingestion, type inference, `UNION ALL BY NAME` and friendlier date SQL. It is the one component to drop if a single engine is preferred later.

### 11.4 Retrieval index (prose)
Produced at ingest from the parser output:
- **Outline**: heading hierarchy (documents), sheet list with row counts (spreadsheets), token counts per section.
- **Chunks**: split on structural boundaries (never mid-paragraph; Docling's own hierarchical/hybrid chunkers are the first choice, spike S15), each with `section_path` and `location` (`s3.2`, `p.14`), stored in `chunks`.
- **Keyword index**: FTS5 over `chunks`.
- **Vector index**: CPU embedding of each chunk into `chunk_vectors`, computed as a second stage so keyword search is available first.
- **Schema chunks**: every table also gets one chunk describing its columns (kind `schema`), so `search` can find "revenue" even in a spreadsheet.
- Search fuses keyword and vector rankings (reciprocal rank fusion) and returns snippets with location and chunk id; `read(handle, chunk=...)` expands around a hit. Citations come for free from `location`.
- Long-document summarization is map-reduce through sub-agents (one clean window per section, short summary back to the parent) — roadmap item.

### 11.5 Skills (the extension mechanism)

**Built on Strands' `AgentSkills` plugin.** The plugin gives us, for free: the SKILL.md format (YAML frontmatter + markdown instructions), discovery from directories, a catalog injected into the system prompt (name + description per skill), an activation tool named `skills` (call: `skills(skill_name="docx-report")`) that returns the full instructions, and activation state kept in `agent.state`. It does **not** register tools: skills are instruction packages, and the tools they refer to must be provided separately. The available skills can be swapped between invocations (`set_available_skills`) and the catalog is refreshed before each invocation. We build a fresh agent per run, so this fits.

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
allowed-tools: doc_new doc_text doc_table doc_chart doc_edit doc_render
metadata:
  version: "1"
  outputs: docx
  needs: duckdb
---
```
`allowed-tools` is informational in Strands, but it is our source of truth for which tools belong to a skill (used by the gate and the linter). Our own fields live under `metadata` so the file stays valid for any Strands-compatible loader.

**Tool registration and the gate**
- All skill tools are registered when the agent is built, so tool definitions never change during a run. This keeps the prompt prefix cacheable and removes any need for runtime tool addition.
- Each skill tool's description starts with its skill tag (`[docx-report] ...`).
- The before-tool-call **gate** vetoes a skill tool whose skill is not activated in this run: `error[not_loaded]: skill "docx-report" is not activated; call skills(skill_name="docx-report") first`. This makes the model read the instructions before using the tools, which is what makes them reliable. Spike S20 measures how often a small model skips activation; if often, auto-activate on first use instead.
- **Budget rule:** all skill tool schemas together must stay <= ~2k tokens. If that is exceeded (many skills), switch on the escape hatch: register a skill's tools only after activation. That needs one of three mechanisms (add tools to the live agent between loop cycles; end the loop after `skills` and rebuild the agent with the new tool set; or one generic `run_skill(skill, tool, args)` executor) and is deliberately not built in v1.

**Lifecycle**
1. **Startup:** `AgentSkills` loads `skills/` (and `skills.dirs`); our linter validates the skills; invalid skills are skipped with a warning, never a crash (do not use `strict=True` in production).
2. **Run start:** restore `active_skills` from the previous `task_state` into the fresh agent's skill state, so a follow-up does not re-activate (spike S9).
3. **Activation:** the model calls `skills(skill_name=...)`. The result holds the instructions and a resource listing; set `max_resource_files` low, because our scripts are reached only through our tools. An after-tool-call hook emits `skill_loaded`, records the skill in `scratch_state.active_skills` and pins the result (section 10).
4. **Run end:** `active_skills` is compacted into `nodes.task_state`.
5. The catalog entries include a `<location>` path to each SKILL.md. It is harmless because the model has no file tools; filter it out if a strict "handles, not paths" rule is wanted.

**Lint rules** (`atlas skills check`, at startup and in CI):
- body <= ~500 tokens; <= 6 tools per skill; all tool schemas of one skill <= ~900 tokens;
- <= 5 arguments per tool, flat (no nested objects), enums for fixed choices, ids as strings;
- tool descriptions <= ~40 tokens; tool names unique across all skills and the core (prefix by domain: `doc_*`, `slide_*`, `chart_*`);
- `name` matches the directory; every name in `allowed-tools` exists in `tools.py` and vice versa;
- tests and evals present.

**Tool contract.** Every tool returns either `ToolOutput(summary, objects, warnings)`, rendered as `ok: <summary>`; or `ToolError(code, message, valid)`, rendered as `error[code]: message. valid: a, b, c`, with codes `not_found`, `bad_arg`, `too_large`, `not_ready`, `not_loaded`, `failed`. Unexpected exceptions become `error[internal]` with the traceback only in the log. Every tool receives a `ToolContext`: run id, workspace paths, read-only DuckDB connection, `ctx.resolve(id)` (enforces branch visibility), event emitter, cancel token, settings snapshot. The model supplies ids only; skills never receive raw paths from model arguments.

**Trust and safety.** v1 skills are first-party trusted code; the model cannot create or edit skills. No network unless a skill declares `needs: network` (reserved for the browser skill). Subprocess scripts run with a timeout and are killed on cancel; renders write to a temp file and rename atomically.

**Testing.** Unit tests with golden outputs (no model); `atlas skills check`; model-facing `evals.yaml` prompts run through the real pipeline, recording pass/fail, steps and tokens. A failing eval usually means the instructions or tool descriptions need work, not the model. These runs also feed the paper's ablations.

**Scaling notes.** The catalog costs ~25 tokens per skill, fine to ~15 skills; beyond that add `find_skill(query)`. Skill-to-skill dependencies are out of scope in v1; shared code lives in `atlas/lib/` (charts, tables, the Draft SDK).

**v1 skill set**
| Skill | Tools | Purpose |
|---|---|---|
| `docx-report` | `doc_new`, `doc_text`, `doc_table`, `doc_chart`, `doc_edit`, `doc_render` | reference skill; template for all later authoring skills |
| `data-export` | `export_table(source, format, name)` | csv / xlsx export of a result table (data never passes through the model) |
| `charts` | `chart_make(source, type, x, y, title)` | standalone chart image objects |
| `pptx-deck` (next) | `slide_*` | same Draft SDK, different block types and renderer |

### 11.6 Draft SDK and the docx skill
Authoring skills share one harness-level **Draft SDK** so a new format only supplies block types and a renderer:
- A draft is a row in `drafts` (`kind`, `spec`, `version`); the output file is a build artifact.
- The skill registers **block types**, each with a JSON schema (docx: `heading`, `paragraph`, `list`, `table`, `chart`, `page_break`). The SDK assigns block ids, validates every mutation against the schema and against referenced sources (existence, columns), and bumps `version`.
- `render(draft) -> (file, VerificationReport)`: writes a temp file, renames atomically, registers the output as an attachment (handle `f2`), emits `draft_rendered`.
- `VerificationReport` is a list of checks `{name, status: ok|warn|fail, detail}`. Generic checks live in the SDK (sources exist, row/column counts match, numbers-in-prose, plan items marked done vs content); skills add format-specific checks.

The docx tools:

| Tool | Arguments | Notes |
|---|---|---|
| `doc_new` | name, template? | creates draft `d1` |
| `doc_text` | doc, kind (`heading`/`paragraph`/`list`), text, level? | the only place the model writes prose; sections <= ~300 tokens |
| `doc_table` | doc, source, columns?, formats?, caption? | `source` = result id/alias; data pulled at render |
| `doc_chart` | doc, source, type, x, y, title, axis labels | PNG via matplotlib (shared `atlas/lib/charts`) |
| `doc_edit` | doc, block_id, fields / `remove` / `move_to` | block ids are server-assigned |
| `doc_render` | doc, path | writes `outputs/<name>.docx`, returns the verification report |

Validation at call time: `doc_chart` checks that source exists, `x`/`y` are real columns, `y` is numeric, categories <= ~30 (otherwise suggests top-N).

### 11.7 Verification report (seed of the verification gate)
The render step's `VerificationReport` includes a **numbers-in-prose check**: every number found in paragraph text is matched against values in the referenced tables (with rounding tolerance); unmatched numbers are reported with the nearest candidates. Later this moves into a `BeforeToolCall`/render hook with `verification_*` events.

---

## 12. Attachments and ingestion

**Pipeline:** upload -> hash and dedupe -> attachment row, extraction `queued`, handle returned -> ingest worker (single process, independent of the run lock) -> `ready`. The UI polls `GET /attachments/{id}` for `status`, `progress` and `embed_status`, and stops polling as soon as everything has settled. Sending a message while an attachment is still parsing is **allowed**: the run waits for its own attachments (default 8s) and, if the wait expires, tells the model which file it cannot read rather than letting it answer blind. A failed ingest shows its error on the chip and can be retried or removed.

Measured end to end, everything local: a 422-byte markdown file is ready in **25ms**, a 1 MB text file in 364ms, a 57 KB 13-sheet xlsx in ~1.06s. Text uploads are effectively instant and no optimisation is warranted; the parser reads 1 MB in 8ms.

**Ingestors** (registry by MIME). All return the same `IngestResult`: `{outline, chunks, tables, warnings, page_count, token_count}`.

| Ingestor | Handles | Notes |
|---|---|---|
| `DoclingIngestor` | PDF, DOCX, PPTX, HTML, images, markdown | two pipelines for PDFs/images (below); DOCX/PPTX/HTML use Docling's own format backends; runs on CPU (`ingest.device`) to protect VRAM; saves the Docling document JSON to disk; tables -> DataFrames -> DuckDB; table text duplicated as chunks |
| `TabularIngestor` | XLSX, CSV, TSV | reads straight into DuckDB (no document model); type inference; unified view; warnings; outline = sheets with row counts; one schema chunk per table |
| `TextIngestor` | txt, md, json, log, code | paragraph-based chunking |

**Docling pipelines (PDFs and images).**
- `standard`: layout analysis + table-structure models + OCR where needed. For born-digital PDFs it copies the embedded text layer, so extracted text is verbatim (nothing is generated). Lighter on memory; the Docling docs suggest it for limited resources and batch work.
- `vlm`: Granite-Docling-258M (IBM, Apache 2.0) looks at each page as an image and generates DocTags, which Docling converts into the document model. Strong on scans, complex layouts, equations, code and chart-to-table, but it *generates* text (IBM notes that small models can hallucinate), and it is slower and heavier.
- `auto` (proposed default): `standard` first; use `vlm` for pages with no text layer or where layout analysis is unreliable. Spike S15 measures both on real documents and decides the default.
- The VLM runs in its own llama.cpp server (GGUF + projector file) and is called through Docling's remote-VLM option (`ApiVlmOptions` with `enable_remote_services=True`), so it never shares a process with Gemma. That the GGUF route works end to end with Docling's DocTags parsing is unverified (S15); the Docling VLM guide documents vLLM and Ollama servers, not llama.cpp.

Rules:
- **Routing by output kind** (11.3). The ingestor declares what it produced; nothing is classified by content.
- **Cache key:** (sha256, parser, parser_version, docling_pipeline, embed_model). Retries and re-uploads never re-parse.
- **Two-stage readiness:** stage 1 (outline, chunks, FTS, DuckDB tables) makes the file `ready`; stage 2 (embeddings) continues in the background (`embed_status`). `search` uses vectors only when complete.
- **Summaries are lazy:** outline and token counts are stored eagerly; a document or section summary is generated by the local model the first time a task needs it (map-reduce for long documents) and cached in `attachment_summaries`.
- **Images:** passed as image blocks if `supports_vision`, otherwise skipped with a `warning`; Docling OCR still indexes any text in them.
- **Large documents:** never inlined. The user message carries a one-line description (`[f1: sales.xlsx, 12 sheets, 1,248 rows - use describe(f1)]`); content is reached only through tools.
- Attachments on older user nodes keep their recorded description, so history is stable across retries.
- Ingestion contention: one worker, CPU only. Expect seconds per PDF page on CPU; progress is reported per page.

---

## 13. Worked example: "From sales.xlsx (12 monthly sheets), build report.docx with a monthly-totals table, a bar chart and a 3-sentence summary."

**Attach:** file saved, hashed; `TabularIngestor` produces tables `f1_Jan..f1_Dec`, unified view `f1_all`, warning "revenue has 2 non-numeric values in Mar", an outline of 12 sheets and 12 schema chunks. Status `ready`. Handle `f1`.

**Send:** `POST /chats/{id}/messages` -> user node, assistant node, run, `run_id` returned; SSE opens. Initial context ~5k tokens: system prompt (with skill catalog), core and skill tool definitions (skill tools are visible from the start, ~1k), empty notepad, the user message with the one-line attachment description.

**Loop** (each step: model reads the whole context, replies with a tool call or final answer; harness runs it and appends the result):

| # | Model call | Result (approx.) |
|---|---|---|
| 1 | `plan([...4 items])` | `ok: plan saved` |
| 2 | `skills(skill_name="docx-report")` | skill instructions (~400 tok, pinned); the doc tools now pass the gate |
| 3 | `describe("f1")` | schema, unified view, 5 sample rows, warning (~300 tok) |
| 4 | `query("SELECT _sheet AS month, SUM(revenue) AS total FROM f1_all GROUP BY 1 ...", save_as="monthly")` | `[monthly] 12 rows x 2 cols` + the rows (~150 tok) |
| 5 | `doc_new("report")` | `ok: created d1` |
| 6 | `doc_text(d1, heading, ...)` | `ok: block b1` |
| 7 | `doc_table(d1, source="monthly", caption=...)` | `ok: block b2, table 12x2` |
| 8 | `doc_chart(d1, source="monthly", type="bar", x="month", y="total")` | `ok: block b3` |
| 9 | `doc_text(d1, paragraph, "<3 sentences>")` | `ok: block b4` |
| 10 | `doc_render(d1)` | `ok: saved outputs/report.docx; table matches monthly; chart source monthly; numbers in text: 3/3 found` |
| 11 | final text | run ends |

Total tool traffic ~2k tokens; peak context ~6-7k of 32k. The 12 sheets never enter the context; at step 7 the model said "put `monthly` here" instead of retyping 12 rows.

**Failure paths:** a 500-row query shows 10 rows + id `r3`; a typo'd column returns `error[bad_arg]` listing valid columns; a repeated identical call triggers the loop nudge; cancel aborts the model request, saves the partial step and ends the run as cancelled.

**After:** one transaction writes final status, steps, assistant node, compacted `task_state` (including `active_skills`); `report.docx` is registered as `f2`. A follow-up ("make the chart horizontal") starts a new run; the data store still holds `monthly` and draft `d1`, the docx skill is re-activated automatically, the notepad summary is pinned again, so the model edits the chart block and re-renders.

**Prose variant:** for twelve PDF reports instead of sheets, steps 3-4 become `outline`/`search`/`read` per report plus `collect("monthly", [...])`; everything from step 5 on is identical.

---

## 14. API surface

| Endpoint | Purpose |
|---|---|
| `POST /chats/{id}/attachments` | upload; returns handle and `status=queued` immediately |
| `GET /attachments/{id}` | status, progress, `embed_status`, warnings, outline |
| `POST /attachments/{id}/retry` | re-run a failed ingest |
| `POST /chats/{id}/messages` | send (text, attachment ids, options) -> `run_id`, 409 (run active). Unparsed attachments are not an error; the run waits for them. |
| `POST /nodes/{id}/edit` | edit user node -> `run_id` or 409 |
| `POST /nodes/{id}/retry` | retry (new assistant sibling) -> `run_id` or 409 |
| `POST /nodes/{id}/select` | switch version via `selected_child_id` |
| `GET /chats/{id}/tree` | visible path + sibling counts |
| `GET /chats/{id}/objects` | catalog (tables, drafts, outputs) for later UI |
| `GET /runs/active` | the single active run, if any |
| `GET /runs/{id}` | status snapshot |
| `GET /runs/{id}/events?after=seq` | SSE with replay |
| `POST /runs/{id}/cancel` | cancel |
| `GET /skills` | catalog (name, description, tools) |
| `GET/PUT /settings` | read/write settings; reports restart-needed keys |

---

## 15. Evaluation switches (for the paper)
Each mechanism can be a switch: result offloading, notepad, hysteresis pruning, verification report, skills vs always-on tools, hybrid vs keyword-only search. This lets the ablation configurations in the research proposal be run without rewriting the harness. Skill `evals.yaml` files double as task fixtures.

---

## 16. Spike checklist (attached to build layers)

Version: assume the latest release; the newest changelog entry found was Python `strands-agents` 1.55.0 (2026-09-08); repository is now `strands-agents/harness-sdk`. Pin the installed version and re-run the checks on upgrades. Each item is answered in the layer shown, with a small script, and the answer is written back into this section.

**Confirmed from the docs**
- `stream_async` yields text, tool, lifecycle and reasoning events (`reasoning`, `reasoningText`) and a final `result`.
- Hook events: before/after invocation, before/after model call (`exception`, `retry`), before/after tool call (`cancel_tool`, `selected_tool`, `interrupt`, `exception`, `retry`, modifiable `result`). `HookProvider` and `Plugin`/`@hook` supported; async callbacks; `HookOrder`; `AfterInvocationEvent.resume`.
- `agent.cancel()` exists; native per-invocation limits (turns, total tokens, output tokens).
- `LlamaCppModel` exists with `params` incl. `top_k`, `cache_prompt`; overflow mapped to `ContextWindowOverflowException`.
- `AgentSkills` plugin: `from strands import Agent, AgentSkills, Skill`; sources are paths, URLs or `Skill` objects; constructor options `state_key`, `max_resource_files`, `strict`; activation tool `skills(skill_name=...)`; `get_available_skills`, `set_available_skills`, `get_activated_skills(agent)`; activation state in `agent.state`; catalog refreshed before each invocation; it does not register tools; `allowed-tools` is informational.
- Docling VLM pipeline: `VlmPipeline` with `VlmPipelineOptions`; remote OpenAI-compatible server through `ApiVlmOptions(url, model, api_key)` with `enable_remote_services=True`; Granite-Docling-258M outputs DocTags. The Docling VLM guide does not document the llama.cpp/GGUF route; the model card says quantized builds for llama.cpp/Ollama/LM Studio exist but gives no instructions.

**Resolved by you:** thinking can be passed per request as an extra request argument (Unsloth's llama.cpp notes); S1 is now a confirmation only.

| ID | Question | Layer | If it fails |
|---|---|---|---|
| S1 | Does the extra-argument route (`chat_template_kwargs.enable_thinking`) work through the model adapter, per request, without restart? | L0 | subclass the model or patch the request body |
| S2 | Does llama-server return reasoning separately (maps to `reasoningText`) or inline in the text? | L0 | split on the think tags ourselves |
| S3 | What does `agent.cancel()` interrupt mid-generation vs asyncio task cancellation? Does llama-server free the slot when the connection closes? | L3 | cancel both; use llama-server's slot API |
| S4 | Name and timing of the message-added hook; does it fire for tool-result messages? | L3 | build steps from the final `result.messages` |
| S5 | Shape of tool errors (`result.status`, `exception`) for `is_error` | L3 | wrap tools so they always return a status |
| S6 | Where token usage per model call comes from | L0 | llama-server's `usage` field and `/tokenize` |
| S7 | Does `Agent(messages=...)` accept a reconstructed history with tool-use/tool-result pairs for the model's chat template? | L0 | normalize the history to the format the template expects |
| S8 | Dependency compatibility: clean venv with FastAPI, uvicorn, pydantic, httpx, DuckDB, Docling, python-docx, matplotlib, sqlite-vec, an embedding runtime; Python version; commit a lockfile | L0 | pin older versions; isolate Docling in its own environment/process |
| S9 | `AgentSkills` state: what is stored in `agent.state[state_key]`; can we write it before the first invocation to restore activation; can a hook read `get_activated_skills(agent)`; does a low `max_resource_files` suppress the resource listing; does the `skills` result reach hooks as an ordinary tool result (needed to pin it)? | L7 | keep our own activation list and inject it into the instructions |
| S10 | Can a before-model-call hook change the prompt for that call (notepad injection)? | L6 | append the block to the last user message |
| S11 | Is a modified `event.result` (after-tool-call hook) what the model sees? (docs say yes) | L5 | wrap tools instead of hooking |
| S12 | DuckDB reading `.xlsx` in the installed version; `UNION ALL BY NAME` across sheets | L4a | openpyxl/pandas into DuckDB |
| S13 | Can large tool-call arguments in the history be replaced with a stub after success? | L6 | keep arguments small (<= ~300 tokens per call) |
| S14 | Does Strands' newer context-offloading support (1.55 changelog) overlap our ResultOffloader? | L5 | keep ours |
| S15 | Docling on your machine: confirmed formats; CPU seconds per page for `standard` vs `vlm` on three documents (born-digital PDF with tables, scanned PDF, DOCX); tables to DataFrames; chunker quality; Granite-Docling GGUF + projector served by llama-server and consumed through `ApiVlmOptions` (does DocTags parsing work end to end?). Decide the default pipeline | L4c, L4e | `standard` only; add `vlm` later or only for scans |
| S16 | `sqlite-vec` loads in your Python build (extension loading is disabled in some builds) | L4d | BLOB vectors + brute-force numpy cosine |
| S17 | Embedding model choice and chunks per second on the i5 | L4d | smaller model; embed lazily on first search |
| S18 | Slowdown of Gemma's tok/s while ingestion and embedding run on CPU | L4 | throttle the worker; pause ingestion during a run |
| S19 | Quality of lazy summaries from the local model on a 20-page document (map-reduce) | L6 | use summaries only for routing, never as facts |
| S21 | Raw failure rate: over a fixed set of ~30 tool-using prompts x 10 runs, thinking on and off, how often is a tool call leaked into `content`, malformed, or answered with an empty message? Compare the server's native parser against the settings in use. | L0b | tune prompts/schemas first; build the extractor only if the 9.1.7 threshold is exceeded |
| S22 | Do retries fix suspects, and does a retry at lower temperature help more than a plain retry? | L0b | keep retries, add the nudge |
| S23 | Does the server parse streamed tool-call arguments correctly (compare streamed vs non-streamed arguments for the same prompt)? | L0b | disable streaming for tool-calling steps; stream only the final answer |
| S24 | What does Strands do with a tool message of empty content in the installed version, and is `"(no output)"` accepted by the chat template? | L0b | normalize in the adapter |
| S25 | Slots: with 4 slots at 32k, is the context per slot 32k or 8k? Does a pinned `id_slot` keep the prompt cache warm across steps and chats? | L1 | set `--parallel 1` (we allow one run at a time) or a unified KV cache |
| S26 | Does reasoning count against `max_tokens`, and how much headroom avoids truncated tool calls? | L0b | raise `max_tokens` or disable thinking for tool-calling steps |
| S20 | Skill gate end to end: the veto message is returned and the small model recovers by calling `skills`; how often does it skip activation? | L7 | auto-activate on first use of a gated tool |

### L0 answers (2026-10-10)

Environment: Python 3.12.10, `strands-agents==1.58.0` (newer than the 1.55.0 noted above; pin this and re-run these checks on upgrade), llama.cpp `b11429-d81235049`, model `unsloth_e2b_qat.gguf` (reported by the agent as "Gemma 3 2B e2b, Q4_0"; the project's model is Gemma 4 E2B, so verify the name/quantization and record the GGUF hash), 32k ctx, 4 slots, served on port 8080. Note: 4 slots may split the 32k context per slot (S25). Scripts: `spikes/raw_probe.py` (raw HTTP), `spikes/s1_thinking.py`, `spikes/s7_history.py`; fixture `scripts/smoke_llamacpp.py`.

| ID | Answer | Consequence |
|---|---|---|
| S1 | **Yes, with one fix.** The server accepts `chat_template_kwargs.enable_thinking` per request. But `LlamaCppModel._format_request` forwards `params` through a strict allowlist (`openai_params` + `llamacpp_specific_params`) that does **not** contain `chat_template_kwargs`, so it is silently dropped. | Subclass the model (`atlas/models/llamacpp_atlas.py`, the spec's "subclass the model or patch the request body" fallback). `set_thinking(True/False)` flips it on a live instance; no restart, no new agent. |
| S2 | **The server separates it; the Strands adapter throws it away.** llama-server returns Gemma 3's `<\|channel\|>thought` block as a separate `reasoning_content` field (and `delta.reasoning_content` when streaming) — it is not inlined in `content`. But upstream `stream()` only reads `delta.content` and `delta.tool_calls`, so the reasoning was discarded, even though `_format_chunk` already knows how to emit `reasoningContent`. | Our adapter re-implements the SSE loop to forward `reasoning_content`, opening/closing a reasoning block around the text. `reasoningText` events now reach the agent, which is what makes `thinking_delta` (section 8) implementable. Delete our `stream()` when upstream fixes this. |
| S6 | **Two places.** Per-call usage rides in the trailing SSE frame as `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`, `prompt_tokens_details.cached_tokens`); upstream already sets `stream_options.include_usage` and drains it into a `metadata` chunk → `usage: {inputTokens, outputTokens, totalTokens, cacheReadInputTokens}`. Independent of that, `count_tokens` hits llama-server's `/tokenize` (needs `use_native_token_count=True`), otherwise it falls back to estimation. | Feed the `usage` event straight from the metadata chunk. `cacheReadInputTokens` is a free measurement of how much of the prompt prefix llama.cpp reused — use it to validate the hysteresis pruning in L6 (section 10). |
| S7 | **Yes, as-is.** `Agent(messages=...)` accepts a history containing `toolUse` / `toolResult` pairs. Verified by capturing a real tool-calling transcript, round-tripping it through JSON, and seeding a fresh agent: the model recovered the stored result and answered correctly. Shapes: assistant message holds `{"toolUse": {toolUseId, name, input}}`; the tool result is a **user** message holding `{"toolResult": {toolUseId, status, content:[{text}]}}`. | The ContextBuilder can rebuild context straight from `steps` rows with no normalization step. Keep call/result pairing intact — the chat template needs both. |
| S8 | **No conflict.** A clean install resolves 99 packages (150 installed) on Python 3.12.10: `docling 2.137.0` (pulls `torch 2.14.1`, `transformers 5.19.0`), `duckdb 1.5.6`, `pandas 3.0.6`, `sqlite-vec 0.1.9`, `fastembed 0.9.0` (ONNX, keeps the embedding runtime off the torch path), `python-docx 1.2.0`, `matplotlib 3.11.2`, `fastapi 0.143.0`. `pip check` is clean. | One environment is enough; Docling does not need isolating. Committed as `requirements.in` (intent) + `requirements.lock.txt` (resolved). |

Two findings that change earlier assumptions:

1. **The server defaults thinking ON.** Omitting `chat_template_kwargs` yields reasoning, so Atlas must send `enable_thinking` explicitly on every request rather than relying on the server default. The live `thinking` setting must therefore always be materialised into the request.
2. **A before-model-call hook cannot swap the prompt directly.** `BeforeModelCallEvent` exposes `agent`, `invocation_state`, `projected_input_tokens` and `cancel` — there is no `messages` field to replace. It does expose `projected_input_tokens` for free. This leans toward the S10 fallback ("append the block to the last user message"); resolve it in L6.

Also confirmed for later layers: `BeforeToolCallEvent` carries `tool_use`, `selected_tool` and `cancel_tool` (so the L7 skill gate can veto), and `AfterToolCallEvent` carries a modifiable `result` plus `duration` (so L5's ResultOffloader has a seam).

Still open at L0: nothing outstanding. Added afterwards: the tool-call guard (section 9.1) and its measurement layer L0b. The sibling project's launch flags were seen only as a hint (port 8080, a different model path); the real launch command is still needed to fix L1's restart-tier defaults.

### L5 answers (2026-10-11)

Tool runtime in `atlas/tools/`: `contract.py` (ToolOutput/ToolError and their two renderings), `context.py` (ToolContext, branch visibility, table-name resolution), `validate.py`, `catalog.py`, `offloader.py` (ResultOffloader), `notepad.py`, `core_tools.py` (the eleven always-on tools), `guard.py`, `runtime.py`. Wired into the run engine at `atlas/run/executor.py`: one `ToolContext` per run, handed to every tool through `invocation_state`.

| ID | Answer | Consequence |
|---|---|---|
| S5 | **Answered, and better than expected.** Strands' `_wrap_tool_result` passes a returned dict through *unchanged* when it has `status` and `content`; anything else is wrapped as `success` with the value serialised. So a tool decides `is_error` outright -- it is not inferred from an exception. A raised exception becomes `Error: {type} - {msg}`, which leaks a Python class name into the model's context. | Tools raise `ToolError` (an `Exception`), and `@guarded` -- applied *under* `@tool` -- catches it and returns the rendered dict. The model only ever sees `ok: ...` or `error[code]: ...`. `ToolError` extends `Exception` precisely so `except ToolError` works; as a plain dataclass it did not, and the guard silently degraded to `error[failed]`. |
| S11 | **The hook is not the right place.** `AfterToolCallEvent.result` is observable but the offloader needs to run *before* the result becomes the tool-result message, and keeping the logic in a wrapper means one code path whether or not a hook happens to fire. | Offloading happens in `ResultOffloader.render`, called by each tool that produces a body, under `@guarded`. The hook only *observes* the finished result and emits `tool_call_finished`. |
| S14 | **No material overlap, and it does not change the design.** Upstream offloading is about a full agent transcript growing past the window. Ours is about a *single tool result* at a fixed budget (400 passthrough / 1.5k hard inline cap), with the property that saving is unconditional and display is conditional. | Keep ours. Even if upstream grows a similar feature, the control-plane/data-plane boundary is where Atlas decides what leaves, and `show`/`query` depend on the catalog entry we create. |

Decisions worth keeping:

- **A result's summary must carry its value, or the model invents one.** The worst bug in the layer, and no amount of golden testing found it. `query("SELECT SUM(revenue) FROM f1_mar")` returned the literal string `ok: 1 rows x 1 cols`. The number was in the tool result and the model never saw it, so it filled the gap: across three runs against a true `425184.67` it reported `29623.19`, `29517.98` and `33196.28`. Three different wrong answers to the same question, all confident. The offloader budgets on *rows*, but an aggregate has no rows -- it has one value, and that value is the entire answer. `_result_summary` now names the value for any one-row result and any result of five rows or fewer, and `keep_summary` stops the offloader replacing it with a shape.
  - Worth stating plainly, because the tooling did not catch it: every tool test asserted on `startswith("ok:")` and on *which* tools were called, never on *whether the answer was right*. A test that only checks the shape of a success will happily pass a hallucinated number. The end-to-end check now compares the model's answer against ground truth read from the spreadsheet with pandas -- not from Atlas, which would only be checking Atlas against itself.
- **Floats are rounded to decimal places, never to significant digits.** `sum(revenue)` over two-decimal money returns `425184.6699999999`, and the model repeats whatever it is shown, so float noise becomes noise in the answer. Two attempts were wrong before one was right: rounding to 6 *significant* digits turned 425184.67 into 425185, and formatting the result with `%g` -- also 6 significant digits -- undid the fix one line later while the unit test still passed, because it tested the wrong function. `FLOAT_DISPLAY_PLACES = 2` is the right unit: a spreadsheet's precision is a count of decimals, not of leading figures. Stored bodies keep full precision.
- **Parsed data is global; working files are per chat.** Auditing the schema showed the whole parsed-file layer in SQLite was already keyed by `attachment_id`, with no `chat_id` anywhere -- `chunks`, `attachment_extractions`, `attachment_summaries` -- and `attachments.handle` is allocated globally (`next_handle` counts every attachment). So `f1_mar` already named exactly one table in the whole installation, and scoping the DuckDB per chat bought nothing while costing correctness: a second chat uploading the same bytes was deduplicated to the first chat's attachment, nothing was parsed for it, and `SELECT SUM(revenue) FROM f1_mar` failed on a table `describe` had just listed. Layout is now `blobs/<sha256>` plus one `duckdb/data.duckdb`; `workspace/<chat_id>/` keeps scratch and outputs. Catalog objects stay chat-scoped, because a query result belongs to the conversation that produced it and branch visibility (11.4) depends on it.
- **One file, many names** (migration 7). Identity is the hash, so `resume.pdf` and `resume_new.pdf` are one attachment sharing one parse -- but `original_name` was written once at insert, so the second name was silently discarded and the file kept being listed under a name the user had stopped using. Overwriting instead would only move the problem: a chat from yesterday that said "resume.pdf" would then find it labelled "resume_new.pdf". So the first name stays canonical and later names become aliases; `list_files` prints them and a handle resolves by any of them.
- **The worker is told where the database is.** The ingest worker runs in a *spawned* process, which re-imports the parent's `__main__`, so anything the parent set up at module level can differ by the time the child runs. Both sides were resolving `duck_path()` independently and silently disagreeing, which writes every parsed table to a database nothing reads. The path is resolved once and passed through the job payload.

- **The SQL guard is the read-only boundary, not defence-in-depth.** Spiked DuckDB 1.5.6 directly: a `read_only` connection blocks INSERT/UPDATE/DELETE/DROP/CREATE and `COPY ... FROM`, but it **still allows `COPY ... TO`** (wrote `C:\Windows\Temp\atlas_escape.csv`) and **still evaluates `sniff_csv`/`glob`/`read_csv` against any path** (`sniff_csv` returned the contents of a file outside the chat). A read-only connection would not have stopped either. The token scan blocks both, and string literals plus comments are blanked before scanning so prose containing "copy" is not a false positive.
- **`statement_timeout` does not exist in DuckDB 1.5.6** (`max_execution_time` and `timeout` neither). The only cancellation lever is `Connection.interrupt()`, so `DuckStore.run_readonly` runs the query on a worker thread and interrupts it at the deadline. Verified: interrupt is prompt, is *not* sticky (a follow-up query works), and lands at operator boundaries so unwinding can overshoot slightly.
- **One connection per file, shared.** DuckDB refuses a second connection to the same file with a different configuration, so a read-write ingest connection and a read-only tool connection to the same chat cannot coexist. `_Handle` in `duckstore.py` keeps exactly one connection per path with a refcount; `read_only` became a policy flag on the store. The tool layer gets a fresh `DuckStore` per `ToolContext`, all sharing the handle.
- **SQL is guarded by statement position, not by substring.** A keyword scan rejected `OFFSET` (contains "set ") and would have rejected a `created_at` column (contains "create"). Now: every statement must *start* with SELECT/WITH/TABLE/VALUES/DESCRIBE/SUMMARIZE, and a separate token scan covers only words that cannot be column names -- ATTACH, COPY, EXPORT, INSTALL, LOAD, PRAGMA, glob, read_csv, sniff_csv and friends. Verified against `OFFSET`, `created_at`, and prose in string literals and comments.
- **Every table name the model writes is resolved before it reaches SQL.** Ingest lowercases (`Mar` -> `f1_mar`), but the model reads `f1_March` out of the user's question and writes it back. `ToolContext.table_name` resolves exact, then case-insensitively, then month-stem (`f1_March` -> `f1_mar`), then unique substring -- and refuses anything ambiguous. `query` additionally rewrites the names in the SQL and retries once, because "Did you mean `f1_apr`?" from DuckDB is an alphabetical neighbour, not a correction. This is what makes the spec's worked example ("total revenue in March") work on a 2B model.
- **Offloading always writes the body.** `store` records where data *came from*, not where the offloaded copy lives: a query result is derived from DuckDB but is only recoverable through `show` if the bytes were written down. Gating `put_text` on `store == "sqlite"` produced catalog objects that existed and had no body -- exactly the "phantom object" the spec forbids.
- **`collect` must not double-insert.** Creating the table from the first row and then appending all rows wrote that row twice. Creation now writes the payload directly.
- **The notepad is persisted at finalize, not at cancel.** `compact_notepad` plus the run's catalog objects go onto `node.task_state`, so the next turn inherits the plan and the facts.
- **Cancellation needed a third mechanism.** `agent.cancel()` stops Strands' loop; cancelling the asyncio task closes the HTTP stream to llama-server. Neither is observable to a blocking DuckDB query, so the run also carries a `threading.Event` that `run_readonly` polls. Three layers, each covering what the others cannot.
- **The system prompt is load-bearing.** It was one sentence, which told the model nothing about *how* to work, and it guessed: `SELECT SUM(Revenue) FROM SalesData WHERE SaleDate LIKE '2024-03-%'` on the first call, having invented a table, a column and a year. `atlas/run/prompt.py` now states the working discipline in seven rules, each traceable to a measured failure. ~350 tokens, in the never-pruned prefix. With it the model calls `list_files`, reads `describe`, and writes the correct SQL.
- **`AfterToolCallEvent.result` is a plain dict, not an object.** Probed it: `getattr(result, "status", "")` returns `""` for every call, so the L3 hook reported `is_error: false` even for a result whose `status` was `"error"`. A tool that *returns* a failure sets no exception, so the dict is the only place it is recorded. `RunEvents._after_tool_call` now reads `result.get("status")` and extracts the text for the preview instead of stringifying the whole envelope.
- **Strands' llama.cpp formatter crashes on `reasoningContent`** (S13). On turn two of any tool-using run the model's own reasoning is replayed into the request and `_format_message_content` raises `TypeError: content_type=<reasoningContent> | unsupported type`, killing the run with `EventLoopException`. `AtlasLlamaCppModel` drops the block -- llama.cpp has no field for it, and replaying the text would spend context re-stating a decision already made -- then strips the empty text it leaves behind. The reasoning still reaches the user as a `thinking` step.
- **The model composes handles with filenames.** Shown `f1  sales.xlsx`, it wrote `describe(target="f1_sales.xlsx")`, got a `not_found`, and told the user it could not find any file. `resolve_handle` now accepts `f1`, `F1`, `f1_sales.xlsx` and `sales.xlsx` (the `_` defeats `\b`, so the handle regex uses an explicit lookahead), and `describe` on a spreadsheet lists its tables and unified view -- "what is in this file" and "what SQL can I write against it" are the same question.

Measured on the real model (gemma e2b, thinking off), against a mixed corpus of `sales.xlsx` (13 sheets, 1,249 rows), `contract.txt`, `notes.md` and `server.log`:

| Question | Tools used | Outcome |
|---|---|---|
| "what is the total revenue in March?" | `list_files`, `describe`, `query` | **425184.67**, matching ground truth read from the spreadsheet with pandas. |
| "where does the contract mention termination?" | `search` (or `read` + `search`) | Correct. Locates clauses 3, 4 and 5, quoting verbatim when asked to and citing section numbers when summarising is enough. |
| "what are the notes about?" | `outline`, `read` | Partial: it lists the sections and asks which one to read, rather than reading all ~80 tokens. A 2B model under-using a cheap tool, not a defect. |

Cross-chat reuse was verified across three chats in one run: chat 1 uploads `sales.xlsx`, chat 2 uploads the same bytes and gets the existing parse with no re-ingest, chat 3 uploads the same bytes under a different name and both names resolve to handle `f1`. All three report the same 425184.67.

Verification (ad-hoc, not committed -- the section 19 ground rules): a golden pass over every tool against a real ingested chat, an end-to-end pass through `RunExecutor` with `FakeModel`, and a 22-assertion clean-install run against the real model over the HTTP API covering the two done-when questions plus cross-chat reuse and the rename case. All green.

The honest summary of how this went: the golden suite passed throughout while the model was confidently reporting numbers that were wrong by an order of magnitude. Every tool worked correctly in isolation and no assertion asked whether the *answer* was right. The bugs that mattered -- the missing aggregate value, the cross-chat dedup, the `reasoningContent` crash, the hallucinated handles -- were all found by running the real model against a real file and reading what it actually said.

### L3 answers (2026-10-10)

Run engine in `atlas/run/` (`context.py`, `events.py`, `hooks.py`, `executor.py`, `mapping.py`, `fake_model.py`); API in `atlas/server/`. `atlas up` now starts both llama-server and the backend, and `http://127.0.0.1:8000/` serves a bare test page for chatting.

| ID | Answer | Consequence |
|---|---|---|
| S4 | **Confirmed.** `MessageAddedEvent` fires for every complete message, *including* tool results, which arrive as a `user`-role message carrying a `toolResult` block. | Steps are built from complete messages in one hook, no delta reassembly. One step row per content block; `reasoningContent` blocks become `thinking` steps, which the ContextBuilder then skips when replaying. |
| S3 | **Both mechanisms are needed and both work.** `agent.cancel()` alone stops Strands' loop but leaves the in-flight HTTP stream open; cancelling the asyncio task alone leaves Strands' state inconsistent. Doing both gave `status=cancelled` with partial output preserved. | `RunExecutor.cancel` calls both. The `run_cancelled` terminal event is written in the same transaction as the status change, so the global lock releases atomically. |
| S5 | **Deferred to L5.** It needs a real tool with a real error path; L3 has no tools yet. | **Answered in L5** -- see the L5 answers above: returning `{"status", "content"}` passes through Strands untouched, so a tool owns `is_error` outright. |

Design notes:

- **Delta coalescing must flush before any non-delta event.** `EventSink.emit` flushes buffered deltas first. Otherwise `tool_call_started` would take a lower `seq` than the `text_delta` before it, and a replaying client would see them out of order.
- **SSE replay subscribes live first, then reads the missed rows**, deduplicating by `seq` (section 8 rule 4). Verified: disconnect mid-run, reconnect with `?after=`, and the union is exactly 1..N with no gaps or duplicates.
- **The start endpoints must be `async def`.** A sync endpoint is dispatched to a threadpool where `asyncio.create_task` has no running loop.
- **Usage is accumulated in the hook provider**, not the executor: it is the only place that sees each model call's metadata, and a tool-using run makes several.
- **The `FakeModel` is part of the codebase**, selected with `ATLAS_FAKE_MODEL=1`, per the section 19 ground rules. `ATLAS_FAKE_DELAY` paces it when a test needs to observe a run in flight (409 on a second start, cancel mid-stream).

Measured on the dev machine: **~72 tok/s generation**, ~130-200 tok/s prompt eval, and llama.cpp reporting `selected slot by LCP similarity, f_sim_best = 0.404` across turns -- the prompt cache is already being reused, which is the mechanism L6's hysteresis pruning has to preserve.

One llama.cpp warning worth carrying into L0b: `control-looking token: 50 '<|tool_response>' was not control-type; this is probably a bug in the model`. If tool-response tokens are not typed as control tokens, that is a plausible contributor to the leaked-tool-call failures of section 9.1.

### L2 answers (2026-10-10)

Schema and repositories live in `atlas/core/`: `db.py` (connection + reentrant transactions), `migrations.py`, `repo.py`, `paths.py`. The interface from section 19 is `open_repo()` returning a `Repo` with `start_run`, `visible_path`, `append_event` and `finalize_run`. ULIDs moved to `atlas/ids.py` as a shared leaf module, because L1 (launch ids) and L2 (row ids) both need it and a layer may not import upward.

Decisions worth keeping:

- **The global lock is the database, not the code.** `CREATE UNIQUE INDEX idx_runs_single_active ON runs((1)) WHERE status IN ('running','cancelling')` (section 5). A read-then-write check also runs first, purely so the common double-send gets a clear 409 instead of a constraint error -- the index remains the only thing making it correct under concurrency.
- **`seq` is allocated by the database.** `UPDATE runs SET last_seq = last_seq + 1 WHERE id=? RETURNING last_seq` inside the same transaction as the `INSERT`, so a concurrent append can neither collide nor leave a hole: a failed insert rolls its increment back. Verified with 8 threads x 25 appends -> seqs exactly 1..200.
- **"Exactly one terminal event" is enforced, not assumed.** A partial unique index on `run_events(run_id) WHERE type IN ('run_completed','run_failed','run_cancelled')`.
- **`finalize_run` is one transaction.** `Database.write()` is reentrant, so helpers called from it join the outer transaction instead of committing early. Verified by injecting a failure with a trigger *after* the terminal event insert: status, `last_seq`, the event and the node's `task_state` all rolled back together, and the finalize then succeeded on retry.
- **Migrations cannot use `executescript`.** It issues an implicit COMMIT before running, which would break the all-or-nothing upgrade; migrations are split into complete statements (`sqlite3.complete_statement`) and applied inside an explicit transaction with their bookkeeping row.
- **The chats/nodes FK cycle** (`chats.root_id` -> `nodes`, `nodes.chat_id` -> `chats`) is bridged by inserting the chat with `root_id` NULL and filling it in a second statement of the same transaction.
- **Only a `completed` assistant may parent a new message.** Section 5 says so, and section 2 says interrupted/failed/cancelled runs are "recovered by retrying", so those leaves raise `parent_not_completed` (422) and the recovery path is retry. Worth remembering when the UI hits it after a crash: the user is deliberately pushed to retry rather than allowed to write past a broken turn.

One bug found while building it: retry originally created *two* assistant nodes, because the origin-specific path made one and the shared path in `start_run` made another. The retry path now only validates and returns the user node; the single new assistant sibling is created in one place.

### L1 answers (2026-10-10)

**Process and log supervision (added while finishing L1).** Children are spawned with **piped** stdout/stderr and re-emitted with a `HH:MM:SS [name]` prefix and `=` banner lines. Piping matters: inherited output bypasses the prefix entirely, which is why llama-server's log used to be indistinguishable from the CLI's own. Readers feed a queue and a single writer drains it, so a slow or blocked sink can never wedge a child's pipe during shutdown. Child output is *not* collapsed or filtered -- llama's verbosity is left alone.

**Startup waiting.** Rather than polling a port that cannot answer for 7-20s while the model loads, the launcher reads llama.cpp's own readiness line (`llama_server: listening on http://127.0.0.1:8080`) and confirms it with a single `/health` call. The line is only a hint -- the format is `srv %12.*s: listening on %s` and the padding varies between builds -- so `/health` is the authority and a silent 5s probe covers a build that never prints it. Measured: **2 HTTP requests for the whole startup**, versus one every 0.2s before. `httpx` logs one line per request at INFO, which was the source of the connection-refused noise; its logger is now silenced.

**The real launch command** is `ext/start_gemma.bat` in the sibling repo, and the shipped `atlas up` argv now reproduces it:

```
llama serve -m <gguf> --mmproj <mmproj> -c 32768 -ngl all -b 2048 -ub 512 -t 6 \
    --host 127.0.0.1 --port 8080 -np 1 -fa on --jinja --reasoning auto
```

Against `llama serve --help`, with these differences from the .bat: `-ngl all` replaces `-ngl 99` (equivalent); `--tools all` is **dropped** (see 9.1.1); `--host`, `--port` and `-np 1` are made explicit so the port is a setting rather than an accident of the default and we never bind `0.0.0.0`. Also note the binary is `llama serve`, not `llama-server` — the latter name is absent from a current install.

| ID | Answer | Consequence |
|---|---|---|
| S25 | **Per-slot context is the full `--ctx-size`; it is not divided.** With 4 slots and `-c 32768`, `/slots` reports `n_ctx: 32768` for each slot, and a 16,825-token prompt was accepted. Confirmed a second way from the server's own startup log under `-np 1`: `llama_server: initializing, n_slots = 1, n_ctx_slot = 32768, kv_unified = 'false'`. The warning in L1 ("never assume per-slot context equals `--ctx-size`") was right to be checked, and the answer is the reassuring one. | Still default to `-np 1`: one global run means one slot, which removes slot polling and contention and keeps reasoning about cache behaviour simple. Per-slot id pinning is therefore unnecessary (and `hash(chat_id) % 8` from the old `config.py` stays retired). |

**Two further L1 findings that change existing text:**

1. **`--reasoning` and `--reasoning-format` are different flags, and the distinction is load-bearing.** `--reasoning on|off|auto` decides whether the chat template may emit thought tags; with `auto` llama.cpp detects the `deepseek` format, and *that* is what populates `message.reasoning_content`. Launching with `--reasoning-format none` would leave S2's passthrough with nothing to read, silently reintroducing the bug L0 just fixed. Settings therefore expose `model.reasoning` (`on`/`off`/`auto`, default `auto`), which is distinct from the per-request `enable_thinking` of S1.
2. **Throughput is dominated by keeping the model on the GPU, not by `-ngl` beyond "all".** Generation is memory-bandwidth bound; raising `-ngl` above "everything that fits" changes nothing. On the dev machine (RTX 3050 Laptop, 4 GB VRAM; i5-11400H, 6 physical cores) the 2.44 GB Q4_0 model plus a 0.92 GB F16 mmproj is close to the VRAM limit, so the ingest VLM (L4e) must stay on CPU as section 3 already requires. `-t 6` matches physical cores. The portable schema defaults are `gpu_layers: "auto"` and `device: "auto"` (omit `--device`, let llama.cpp pick the backend), which falls back to CPU on a machine with no GPU — better than hard-coding `0`, which would force CPU even where a GPU exists.

---

## 17. Roadmap and open topics

1. **RAG over a persistent library (to design; does not block the base).** The base already contains the pieces: the same ingest pipeline and `chunks`/FTS5/vector tables with `scope='library'` reserved. Remaining design: library management, re-indexing when source files change, cross-chat search permissions, citation format in answers.
2. **Factual memory (to design).** What is remembered about the user and past tasks, who writes it, how it is retrieved without eating the context budget, how mistakes are corrected. Likely reuses the SQLite/FTS5/vector machinery.
3. Verification gate (hooks + `verification_*` events) on top of the render report.
4. Sub-agents as child runs (`parent_run_id`, `agent` field in the envelope), including map-reduce over long documents.
5. More skills (pptx, pdf forms, browser); optional code-runner escape hatch with a pre-tested helper library.
6. Automations: scheduler creating runs without a frontend (supported as is).
7. Optional: separate worker process for runs, event compaction after terminal state, checkpoint/resume (out of scope today).

## 18. Open questions
- Cancelled partial answer as a parent for new messages? (Currently no.)
- Event retention: keep everything in v1; compact deltas after terminal state later?
- Thinking toggle when `supports_thinking` is false: hide or disable?
- Per-result display budget, window split, `skills.pinned_token_cap` and the chunk size need tuning against real runs.
- Ingestion events: polling is enough for v1; add an SSE stream later if the UI needs it.
- Default Docling pipeline for PDFs (`standard`, `vlm` or `auto`): decided by spike S15 on real documents.

---

## 19. Build sequence (layer by layer)

**Ground rules**
- Each layer is runnable and testable on its own; a layer never imports from a higher one.
- Use a scripted `FakeModel` (returns canned text and tool calls) for every test that does not need the real model, so tests are deterministic and need no GPU. The real model is used for smoke tests and evals only.
- Spikes are answered inside the layer that needs them (section 16), and the answer is written back into this doc.
- Keep a log of real-model runs from the start (prompt, steps, tokens, outcome); it is the raw data for the paper.

**Suggested repository shape**
```
atlas/
  cli/        launcher, settings
  core/       sqlite schema + repos, tree ops, events
  run/        context_builder, executor, event_sink, hooks
  ingest/     worker, ingestors/, chunking, embedding
  tools/      runtime, offloader, core_tools/
  skillrt/    AgentSkills wiring, gate, Draft SDK
  lib/        charts, tables
skills/       built-in skills (docx-report/, data-export/, charts/)
tests/
```

**Dependencies:** L0 -> L1 -> L2 -> L3; L0b now follows L6 ((L5 + L6) -> L0b -> L7); L2 -> L4; (L3 + L4) -> L5 -> L6; L5 -> L7 -> L8. L4 is independent of L3, so it can be built in either order or in parallel.

### L0 Smoke test (about half a day)
- **Build:** pinned virtual environment + lockfile; hand-start llama-server with your model; a ~60-line script with a Strands agent, `LlamaCppModel` and one dummy tool that prints every stream and hook event.
- **Answers:** S1, S2, S6, S7, S8.
- **Done when:** thinking toggles per request without a restart; you know where reasoning and usage appear; a reconstructed history with a tool call/result pair is accepted; the lockfile resolves with Docling, DuckDB, FastAPI, python-docx and matplotlib installed together. Keep the script as the first test fixture.

### L4c Rich documents (Docling `standard`) — S15 measured 2026-10-11

Measured before building, as the layer requires. Machine: i5, CPU only, no GPU acceleration configured. `docling 2.137.0`, `docling-ibm-models 4.0.3`, `docling-parse 7.22.2`, `torch 2.14.1`, `transformers 5.19.0`.

**CPU seconds per page, `standard` pipeline (warm -- models already downloaded):**

| document | pages | convert | per page | tables found |
|---|---|---|---|---|
| synthetic, prose only | 2 | 4.0-4.9s | **~2.4s** | 0 |
| synthetic, one 24-row table per page | 3 | 26.3-31.3s | **~8.8-10.4s** | 5 |
| real paper (`exp1.pdf`) | 6 | 19.1-26.7s | **~3.2-4.5s** | 1 |
| real paper (`exp2.pdf`) | 9 | 26.7s | **~3.0s** | 1 |

**First use is dominated by downloads, not by parsing.** The first `standard` run took **394s** for a 3-page document; the same document warm took **26.3s**. The difference is `docling-layout-heron` (328 MB) and `docling-models` (342 MB) being fetched from the Hub, plus RapidOCR's three ONNX models. Warm converter construction is 0.15-0.41s and is not a factor. This is why the cost has to be measured warm: a cold number would make `standard` look 15x worse than it is, and a user who has parsed one PDF never pays it again.

**Decision: `standard` is the default, and it is affordable.** ~3-4.5s/page on real documents is fine for a background worker, and prose is cheaper than tables. A 20-page scanned-style document is 60-90s. No reason to reach for the VLM on cost grounds for born-digital input.

**Tables reach DataFrames, but page-spanning tables fragment.** `export_to_dataframe()` works and the cells are correct. The failure mode is structural: one 24-row table per page across 3 pages came back as **five** tables of shape 24x5, 8x5, 16x5, 18x5, 6x5. The rows are all there and correct (24+8+16+18+6 = 72 = 3x24, and every `Region-NN` appears exactly 3 times in the markdown), and each fragment carries the full header -- but the table is split. This matters for L4c because each fragment would become its own DuckDB table, so `SELECT SUM(x) FROM f1_table` silently reads a fraction of the data. L4c must decide explicitly whether to merge adjacent same-header fragments, and `describe` must be able to say a table is a fragment of a larger one.

**S15 part 2: the VLM needs a separate model, and Gemma is not it.** Read from the installed source rather than inferred. `docling_core` defines a closed output vocabulary: **30 layout tags** (`<text>`, `<title>`, `<table>`, ...) and **13 table tokens** (`<fcel>`, `<ched>`, `<nl>`, ...). Every element must be emitted as `<loc_a><loc_b><loc_c><loc_d><tag>content</tag>` -- four bounding coordinates plus a tag from that fixed set. That is a *fine-tune*, not a format:
- `ApiVlmOptions` does accept any OpenAI-compatible endpoint (default `http://localhost:11434`), so pointing it at our own llama-server is expressible. It would not work. llama.cpp can enforce the output *shape* via `json_schema`/`grammar`; it cannot make a 2B model emit four *correct* coordinates for every element. Grammar guarantees the output parses, never that it is right.
- Cost, at the density of one 24-row table: ~148 elements, ~2,100 output tokens, **~24.5s/page** at the measured 86 tok/s, before prompt eval on the page image.
- `smoldocling` is not installed, and no Granite-Docling weights are in `llm/` (only `gemma/` 2.6 GB and `agents_a1/` 2.7 GB). Note also that the VLM is not one download: `table_structure_model_granite_vision.py` is a second, smaller Granite Vision model used for tables alone.

So L4e keeps its plan (separate Granite-Docling, its own llama-server, on demand) and `auto` keeps its meaning: **`standard` first, `vlm` only for pages with no text layer.** The spec's assumption that a separate model is required was correct.

**Two things L4c inherits, recorded so they are not discovered as bugs later.** `docling` pulls `torch 2.14.1` and `transformers 5.19.0` into the same venv the run engine depends on; `pip check` was clean at L0 but the stack is now shared with a heavy ML tree, and L4c should confirm the L5 tool runtime still imports cleanly afterwards. And the Hub warns that this machine cannot use symlinks, so the cache is in degraded mode and `document-timeout` should be set rather than assuming a fast first run.

### L0b Tool-call reliability measurement (DEFERRED until after L6, decided 2026-10-11)

**Why it moved.** The leaked-call and empty-result failures are intermittent and appear mostly in long tool chains with a filling context. A fixed set of short prompts would report a low failure rate and give false confidence. Measuring is only meaningful once L6 exists, because the failure conditions (many tool calls, a context near its limits, pruned history) are exactly what L6 produces. Until then no guard work is done.

**What this changes in the plan.**
- The measurement set must include **long chains**: 15-40 tool calls per run, context fill at 25%, 50% and 75% of the window, with and without pruning, thinking on and off.
- Counting happens over **whole runs**, not single calls: report "runs with at least one leak" and the call index at which the first leak occurred. Add the run's context size at that moment.
- Cheap data collection that does not alter behaviour may be added at any time: log (do not act on) any model response that has no structured tool call but contains a marker from section 9.1.3, and any empty tool result. This is observation only and is allowed before L6; it makes the later measurement far easier. Not required.
- Risk accepted until L0b: a leaked call ends a run silently as finished, and an empty tool result may break a run. Both are known and recoverable by retry from the UI.
- The decision gate in 9.1.7 stands, with the thresholds measured on long chains.

**Original scope (unchanged otherwise):**
- **Build:** `spikes/tool_reliability.py`: ~30 tool-using prompts (single call, two chained calls, empty-result tools, large arguments, tools with enum arguments) run 10 times each against the real llama-server, thinking on and off, streaming and non-streaming. Records per run: structured call present, leaked marker found, empty response, empty tool result handling, retry outcome. Output: a table of failure rates per category. Also builds the leak/format fixtures from section 9.1.6 for the `FakeModel`.
- **Answers:** S21, S22, S23, S24, S26.
- **Decision gate:** compare the post-retry failure rate with the 9.1.7 thresholds. Below ~2%: ship prevent + empty-result fix + detect + retry + fail-loud only. Above: build the extractor (time-boxed). Far above: Plan B.
- **Done when:** the failure table is committed and the decision is written back into section 9.1.

#### Interlude: sending is not blocked by parsing (2026-10-11)

L0b was set aside mid-flight for a usability defect found by using the thing rather than by measuring it; it was then deliberately deferred until after L6 (see the L0b note above). Recorded here because it changed a spec decision.

**How long an upload takes, measured.** Everything is local, so the expectation was that a text file is effectively instant. It is. End to end through the HTTP API, on never-before-seen bytes (an already-ingested file is deduplicated and returns in ~3ms without parsing, which flatters the number):

| file | size | upload | parse | total |
|---|---|---|---|---|
| `notes.md` | 422 B | 11ms | 14ms | **25ms** |
| `contract.txt` | 1.2 KB | 11ms | 14ms | **25ms** |
| `server.log` | 929 B | 9ms | 14ms | **23ms** |
| `sales.xlsx` | 57 KB, 13 sheets | 12ms | 1052ms | **1063ms** |

The parser is not the cost. `TextIngestor` reads 1 MB in **8ms** (measured directly, warm); the 1 MB end-to-end figure is 364ms, and that is chunking plus a warm worker spawn, not parsing. So the 25ms figure is the honest one for text and no optimisation is warranted there -- the fix was never about speed.

**The defect: attachments were not sent with the message at all.** The frontend's `send()` posted `{text, options}` and no `attachment_ids`. The model was never told any file existed, and answered confidently from nothing. The server's `_require_attachments_ready` gate -- which would have returned 422 -- never fired, because nothing was passing ids to it. A test that asked "did the run succeed" would have passed throughout.

**The 422 was the wrong shape anyway.** Fixing only the frontend would have made every send during a spreadsheet's ~1s parse fail with 422: a send button that appears broken for a second, for reasons the user cannot see. The wait belongs inside the run, where the message has already been accepted and the event stream is already open, so it delays the first token instead of the user.

**Settled design.** `Repo._check_attachments_exist` now checks only existence; `RunExecutor.settle` waits (default 8s, `ATLAS_SETTLE_TIMEOUT_S`) for the run's own attachments and returns anything still pending, which is injected as a turn naming each file and its status. Verified both branches against the real model:
- *settles in time* -- `sales.xlsx` sent the instant upload returned, answer `425184.67`, matching ground truth.
- *wait expires* (timeout forced to 0, fresh 57 KB upload still `queued`): the model replied *"I am unable to answer this question because the attachment `f14: pending_probe.xlsx` is still being prepared and is not yet readable."* No number, no tool call on the unreadable file. That is the whole point: a wrong-but-confident answer is worse than a slow one.

**Showing a handle, not a ULID.** The user turn rendered attachments as `[attachment 01M4MX5X9DQ...]`, and the model passed that id straight to `outline`, which every tool rejected. Two fixes, both right: the user turn now renders `[attachment f2: contract.txt]` (handle first), and `resolve_handle` accepts the raw attachment id as a last resort, since it is the one identifier the model can reach without calling a tool first. The model now writes "the sections in `f2: contract.txt`".

**Polling.** The UI ran a blanket `setInterval(loadAtts, 700)` for a fixed 60s regardless of state -- 9-20 `GET /attachments/...` per upload in the server log, which is the poll traffic visible in the network tab. It now polls at 300ms and stops the moment everything is `ready` or `failed`, which for a text file is one or two requests.

### L1 Launcher and settings
- **Slots:** decide `--parallel` and `id_slot` here (S25). Atlas runs one run at a time, so one slot at full 32k context is the default unless the test shows a unified cache keeps full context per slot. Never assume per-slot context equals the `--ctx-size` flag.
- **Pinning:** `launched.json` records llama.cpp build, GGUF path and hash, mmproj hash and the full flag list.
- **Build:** `settings.json` schema with tiers and a validator; CLI that spawns llama-server (waits for `/health`), the backend and the client; `launched.json` with `launch_id`; process-group / job-object kill; restart-required diff.
- **Interface to the next layer:** a `Settings` object (restart part + live part) and `launch_id`.
- **Tests:** killing the CLI leaves no orphan processes and frees VRAM; editing a restart-tier key shows "restart required"; invalid settings fail fast with a clear message.
- **Done when:** `atlas up` and Ctrl+C are reliable on both Windows and Linux.

### L2 Persistence core (no model involved)
- **Build:** SQLite schema + migrations (section 5); repository layer for chats, the node tree (send / edit / retry / select, visible path), runs with the partial-unique-index lock, `run_events` append with `seq`, and a catalog stub.
- **Interface:** `Repo.start_run(...)`, `Repo.visible_path(chat)`, `Repo.append_event(...)`, `Repo.finalize_run(...)` (single transaction).
- **Tests:** sibling counts after edit and retry; `selected_child` traversal; a second concurrent `start_run` fails and maps to 409; `seq` stays gap-free under concurrent appends; `finalize_run` is atomic (inject a failure mid-transaction); startup recovery marks leftover runs `interrupted`.
- **Done when:** the tree, lock and event tests are green. This layer pays back the most per hour of effort, so write it carefully before any agent code.

### L3 Run engine without tools (the "basic chat pipeline")
- **Guard (slim): deferred together with L0b** (adapter-level suspect detection, retry (max 2), never-empty tool results, `guard_event`, `tool_call_malformed` failure; section 9.1). The extractor is added only if L0b says so.
- **Build:** ContextBuilder v0 (path -> messages, thinking skipped, no pruning), RunExecutor (fresh agent per run), EventSink (coalescing, broadcast), SSE endpoint with replay, step-building hooks, cancel, failure mapping, and the endpoints `messages`, `edit`, `retry`, `select`, `cancel`, `runs/active`, `tree`.
- **Answers:** S3, S4, S5 (with a dummy tool).
- **Tests (FakeModel):** a leaked tool call is detected and retried; three leaks in a row end as `run_failed` (never a silent finish); an empty tool result becomes `(no output)` and the run continues; the run survives a dropped SSE connection; replay has no gaps and no duplicates; cancel mid-stream gives status `cancelled`, a saved partial step and a released lock; a model error gives `run_failed`; a simulated crash gives `interrupted` after restart; 409 on a second start. **Real-model smoke:** five turns, edit turn 2, retry turn 3, switch branches, and check that the context sent to the model is correct for each branch.
- **Done when:** you can chat through curl or a bare test page with edit, retry and cancel working and branch contexts correct.

### L4 Ingestion (independent of L3)
- **4a Tabular:** `TabularIngestor`, DuckDB tables, unified view, quality warnings, attachment endpoints and the single-worker queue (S12).
- **4b Text:** `TextIngestor`, `chunks` table, FTS5.
- **4c Docling `standard`:** outline, chunks, tables -> DuckDB, table text chunks (S15 part 1).
- **4d Embeddings:** second-stage embedding and hybrid search (S16, S17).
- **4e Granite-Docling VLM (optional, may slip):** on-demand llama-server, `auto` policy, decide the default pipeline (S15 part 2, S18).
- **Interface:** `IngestResult`, `search_chunks(target, query)`, `outline(handle)`, the DuckDB table registry.
- **Tests:** `sales.xlsx` -> 12 tables + unified view + warnings; a 50-page PDF -> outline and chunks, and `search` finds known phrases with the right page; a DOCX table appears as a DuckDB table and a `table_text` chunk; re-upload is a cache hit; an ingest failure shows on the attachment; an unfinished attachment blocks send.
- **Done when:** a corpus of about ten sample files (xlsx, csv, born-digital pdf, scanned pdf, docx, pptx, txt) ingests with sensible outline, chunks and tables, and per-file timings are recorded.

### L5 Tool runtime and core tools
- **Build:** `ToolContext`, `ToolOutput`/`ToolError`, argument validators with "valid options" errors, ResultOffloader (S11, S14), the core data tools (`list_files`, `outline`, `read`, `search`, `describe`, `query`, `show`, `collect`, `plan`, `note`), catalog with branch visibility, notepad state, and `AgentSkills` wired with an empty test skill so the `skills` tool exists.
- **Tests:** golden tests per tool; results over ~400 tokens are offloaded and recoverable through `show`/`query`; every error lists valid options; SQL is read-only (DROP, ATTACH and COPY fail) with timeouts; branch visibility holds.
- **Done when:** with the real model, "what is the total revenue in March?" and "where does the contract mention termination?" complete using only core tools.

### L6 Context management
- **Build:** regions and budgets, demotion with stubs, hysteresis pruning, history-summary cache, loop detector, notepad injection (S10), authored-argument stubs (S13), pinned-result exemption for skill bodies, lazy summaries (S19).
- **Tests:** a synthetic 40-step run stays under 75% of the prompt budget; the prompt prefix is byte-stable between consecutive steps (assert on the actual request bodies); tool calls and results are never orphaned; summaries are cached across retries; the loop detector fires on a repeated identical call.
- **Done when:** a deliberately long task (about twelve chained queries plus three document reads) completes within 32k with the real model and `context_built` events show what was pruned.

### L7 Skills and authoring
- **Build:** skill gate hook, `active_skills` restore (S9, S20), `atlas skills check` linter, Draft SDK, `docx-report` skill with the verification report, outputs registered as attachments.
- **Tests:** golden docx renders (open with python-docx and check the blocks); the gate's veto message; a follow-up run reuses the activation; the sales example end to end with the real model, 10 repeats.
- **Done when:** the success rate on the sales example is recorded and every failure is categorized (tool misuse, wrong query, unclear instructions, harness bug). Fix instructions and tool descriptions first, harness second.

### L8 More skills, evals, hardening
- **Build:** `data-export`, `charts`, an evals runner over every skill's `evals.yaml`, linter in CI; then `pptx-deck`.
- **Done when:** `atlas skills check` is clean and there is an eval report per skill.

### After the base
Persistent-library RAG, factual memory, sub-agents, the verification gate, automations (section 17).
