# server/ — the HTTP API

FastAPI. It owns runs (one at a time, outliving the browser), the event
stream, and the routes. Everything else is imported from `agent/`.

```
app.py            create_app: middleware, lifespan, and each area's routes registered
state.py          Atlas: settings, chat store, runs, MCP; the run body (build, stream, record)
schemas.py        request bodies (Pydantic)
views.py          what the API returns for a turn and a run
routes/           one module per area, each with register(api, state, ...):
                  chats, files, turns, runs, settings (+ models, restart), health,
                  extension (pairing, profile, fill, pdf, table), integrations (skills, MCP),
                  spa (the built web UI)
services/         prompt.py (attachments, @ mentions, PDF links, media for the model),
                  workspace.py (what a run created or changed), settings_service.py
runs.py           Run and RunManager: event buffer, cancel, replay
events.py         Strands stream events -> flat API events
transcript.py     fold events into a turn's display parts (mirrored in the client)
security.py       the request guard: Host, Origin, the pairing token
main.py           ASGI entry: `uvicorn server.main:app` (never with --reload)
```

The routes are closures over the state, moved verbatim out of `create_app`;
turning them into FastAPI dependencies (`Depends(state)`) is a later refactor.

## Runs

A run is an asyncio task plus an in-memory event buffer.

- The agent is built in a worker thread (`asyncio.to_thread`): building
  restores a snapshot from disk, and doing that on the event loop stalled
  every open stream.
- Closing the browser does not touch a run. A reopened client sends the first
  sequence number it has not seen and gets everything from there, then live
  events — no gaps, no duplicates.
- One run at a time; a second start is a 409, checked *before* the tree is
  changed so a refused send leaves nothing behind.
- When a run ends, its folded transcript and stats are written to the turn
  (`render_json`, `stats_json`, which holds the run's id and each model call's
  own numbers). A backend crash leaves the turn `interrupted`; at the next start
  it is shown from its trace, and retry runs it again.
- **Every run has a trace** (`agent/common/trace.py`): one JSON line per record
  in `<data>/traces/<chat>/<turn>-<run>.jsonl`, flushed as it happens. Every run
  event, the exact body of every model request, every response (text, reasoning,
  tool calls, finish reason, llama's own `timings`), every policy decision that
  rewrote, asked or refused, with the answer. Never a header, so never the key.
  Deleted with the chat, and after 14 days. `atlas trace` reads it; `atlas
  replay RUN --call N` sends a call's saved request again through
  `POST /traces/{run}/replay` (the key lives only here; not an extension route).

## Events (`GET /api/runs/{id}/events?after=N`)

Server-sent events, each `{"seq": n, "type": ...}`:

| type | fields | meaning |
|---|---|---|
| `run_started` | `chat_id`, `turn_id` | the agent is built |
| `call_start` | | a model call begins (marks where a retried call is cut back to) |
| `model_retry` | `reason`, `attempt`, `of` | the last model call is discarded and repeated |
| `resumed` | `reason` | the done check, the provenance rail or failure recovery sent the turn back once |
| `tainted` | | outside content entered the chat: from now on risky actions ask |
| `notice` | `level`, `text` | a guardrail's note for the user (instructions found in a source, figures with no source) |
| `client_call` | `id`, `op`, `args` | a page operation for the side panel to run in the tab; the run waits for its POST |
| `thinking_delta` | `text` | reasoning |
| `text_delta` | `text` | answer text |
| `tool_start` | `id`, `name`, `args`, `at` (epoch ms) | a tool call |
| `tool_args_delta` | `id`, `name`, `args` | arguments still arriving |
| `tool_end` | `id`, `name`, `status`, `text`, `at` | the result; the stored part gets `ms`, how long the call took |
| `approval_request` | `id`, `kind` (`install`, `access`, `tool`, `page`), `command`, `folder?`, `access?` (`read`/`write`), `chat` (Allow for this chat offered), `timeout`, `expires_at` | the tool policy needs the user's answer; the run waits |
| `approval_result` | `id`, `decision` (`allowed`, `allowed_chat`, `denied`, `expired`) | the answer, or the timeout |
| `stats` | `context_used`, `context_size`, `prompt_tokens`, `completion_tokens`, `tokens_per_second`, `prompt_per_second`, `model_calls`, `duration_ms` | at most 4/s while generating, and once at the end |
| `usage` | `input`, `output`, `total` | per model call, from Strands |
| `done` / `error` | `status`, `message` | always last |

Strands reports each reasoning token twice (a raw event and a normalised
one); `events.py` translates only the raw one. Translating both is what put
"TheThe user user" on screen.

## Routes (all under `/api`)

| Route | |
|---|---|
| `GET /health` | `active_run` with its chat title and tokens/s (the start screen's run line) |
| `GET /chats`, `POST /chats` | list (each with its newest turn's `last_status`), create |
| `GET /outputs` | files runs made lately, across chats, still on disk; inputs a run downloaded to read are left out. Web UI only |
| `GET /chats/{id}` | the visible path: each turn with `render`, `stats`, `version`, `versions`, and the active run |
| `PATCH /chats/{id}` | rename |
| `DELETE /chats/{id}` | the chat, its snapshots, its files, and parsed documents no other chat owns |
| `GET /chats/{id}/export`, `POST /chats/import` | a chat with every version and its Strands snapshots; an import can be continued |
| `POST /chats/{id}/files`, `GET /chats/{id}/files/{path}` | upload into the chat's workspace (a pdf/docx/xlsx is queued for ingest); a file as a download (raster images inline) |
| `GET /chats/{id}/ingest?names=a.pdf,b.docx` | how far each attachment's parsing has got: `{name: {status, done, total}}` (the composer's chips; not open to the extension) |
| `GET /chats/{id}/workspace` | every file in the workspace, newest first. Outlives edits |
| `POST /traces/{run}/replay?call=N` | a run's model call N sent again as saved; then and now (`atlas replay`). 409 during a run. Not open to the extension |
| `POST /chats/{id}/files/import` | `{url}`: a PDF by its link (`file://` copied, `http(s)://` downloaded) into the workspace, as an attachment |
| `DELETE /chats/{id}/files/{path}` | remove an upload before it is sent |
| `POST /chats/{id}/messages` | send `{text, files, refs, thinking}` → `{run, chat}` |
| `POST /turns/{id}/retry` | last turn only → `{run, chat}` |
| `POST /turns/{id}/edit` | `{text, files?, thinking}`, destructive → `{run, chat}` |
| `POST /turns/{id}/select` | `{delta}` → the chat view |
| `GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/cancel` | |
| `POST /runs/{id}/approvals/{approval_id}` | `{allow, scope}`: answer an approval request; `scope: "chat"` counts only where the card offered it |
| `GET /pairing`, `POST /pairing/reset` | the browser extension's pairing token (not readable by the extension) |
| `POST /runs/{id}/calls/{call_id}` | the client's result for a `client_call` (a page operation) |
| `GET /profile`, `PUT /profile` | the user's details for fill suggestions (web UI only; the extension cannot read them) |
| `POST /chats/{id}/moments` | a YouTube video's key moments, saved as a finished turn: chapters, else one model call; no run |
| `POST /extension/fill` | `{fields, title}` -> `{values, missing}`: one schema-constrained model call; nothing is filled here |
| `GET /extension/pdf?url=` | a PDF's bytes for the extension's viewer: a `file://` one, or a web one it could not fetch; PDFs only, 100 MB at most |
| `POST /extension/table` | `{rows, title, url, format, folder}`: a page's table saved as xlsx/csv, no model |
| `GET /models` | the models in the models folder, which one is running, which is selected |
| `POST /restart`, `GET /restart` | ask `atlas start` to restart llama-server and the backend; how the last restart went |
| `GET /settings`, `PUT /settings` | flat dotted keys; any key can be written (RESTART keys are saved, applied at the next start) |
| `PUT /secrets/exa` | `{key}`: the Exa key for web search (empty clears it). Write-only; `GET /settings` says only `web.exa_key_set` |
| `GET /skills`, `POST /skills/install`, `POST /skills/upload`, `PUT /skills/{folder}`, `DELETE /skills/{folder}`, `POST /skills/{folder}/requirements` | |
| `GET /mcp`, `POST /mcp`, `DELETE /mcp/{name}`, `PUT /mcp/{name}`, `POST /mcp/{name}/reconnect`, `PUT /mcp/{name}/tools/{tool}`, `GET /mcp/registry?q=` | a tool's `{mode}` is `on`, `ask` (approve each call) or `off` |

Send, retry and edit return the updated chat view with the run, so the client
replaces the old answer at once instead of waiting for the run to finish.

What the model is told, built per run and never stored as `user_text`:

- **Attachments** (`_agent_text`): names and paths in the `/c/Users/...` form.
  Images and audio are sent as content blocks after the text instead, so a
  voice recording with an empty prompt is a complete message.
- **Passages** (`refs`, from the former preview panel; older turns only), with their file's path,
  ready for the edit tools.
- **@ mentions** (`_mention_guidance`): `@name` in the text that matches a
  skill, tool or MCP server becomes an explicit instruction. Resolved at run
  time, so a retry or an edit gets the same one; unknown names are ignored.

Each run also records the files it created or changed in the workspace
(`stats.files`), for the download chips.

## Who may call (`security.py`)

Every request: the Host must be 127.0.0.1 or localhost (no DNS rebinding);
an Origin must be the web UI's own (the backend's port, or Vite's), or a
browser extension carrying the pairing token; other sites get 403. A request
without an Origin that a browser marks `cross-site`, or `none` on a fetch (what
Edge sends for an extension's GET), needs the token too. Local programs send no
fetch metadata and pass; so does an address typed in the address bar.

The token is accepted only as `Authorization: Bearer`, never in a URL, and
opens only what the side panel uses (`EXTENSION_ROUTES`): chats, turns, runs,
a chat's files, reading settings, and the extension routes. Settings writes,
MCP, skills, restart, pairing, the profile and chat import/export are the web
UI's alone. In the panel, images and downloads are fetched with the header and
shown from a blob (`features/chat/FileLink.tsx`).

A message sent with `page: {url, title, content, kind}` (from the extension)
carries the page itself (`agent/prompt/page.py`: marked as page content, the chat
tainted at once, a long page saved to the workspace, an unchanged page not sent
twice) and adds the page tools to that turn; a page tool emits `client_call {id, op, args}` and waits
for the POST back, like an approval.

## The web UI

The backend serves the built UI (`client/dist`) at `/`, with `index.html`
for any page route, so `atlas start` needs no Vite. The build is looked up per
request. `--dev` runs Vite on its own port instead, proxying `/api` here.

## Non-Obvious Invariants & Footguns

- **Check the run slot before changing the tree.** Send, retry and edit call
  `ensure_run_slot()` before inserting a turn; a refused send that inserted first
  left a phantom `running` leaf.
- **Only a completed turn can be continued.** A cancelled or failed turn has no
  snapshot; sending under it is a 409. Retry or edit it instead.
- **`render_json` is for people only.** It is never given back to the model:
  Strands' snapshot is the history. Changing what the UI shows changes nothing
  the model sees, and the other way round.
- **A tool result's input fence is the model's, not the person's.**
  `events._result_text` strips `<untrusted ...>` before a result reaches the UI or
  the stored render. A new path that shows tool results must strip it too.
- **The trace never holds a header.** The llama key is only in the backend's
  environment; `atlas replay` goes through `POST /traces/{run}/replay` for that
  reason. Do not log request headers anywhere.
- **The extension's token opens `EXTENSION_ROUTES` only, and only as a header.**
  A new route the panel needs must be added there deliberately; settings writes,
  pairing, the profile, MCP and skills stay web-UI-only.
- **A settings write to `access.*` wakes the folder index**
  (`state.index.wake()`), so new folders are searchable at once.
- `created_at` is epoch **milliseconds**; `?after=` is the first sequence number
  the client has **not** seen.
- **Never `uvicorn --reload` on Windows.** Its worker's event loop cannot start
  subprocesses, so every subprocess fails with an empty error. The backend logs
  an error at startup if it finds itself on that loop.
- **One SQLite connection, WAL, closed on shutdown.** A surviving backend held
  `atlas.db` open, and deleting it failed with `EBUSY`.
