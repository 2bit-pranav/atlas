# server/ — the HTTP API

FastAPI. It owns runs (one at a time, outliving the browser), the event
stream, and the routes. Everything else is imported from `agent/`.

```
app.py         Atlas state, chats/turns/runs/settings routes, the run body
extensions.py  skills and MCP routes
runs.py        Run and RunManager: event buffer, cancel, replay
events.py      Strands stream events -> flat API events
transcript.py  fold events into a turn's display parts (mirrored in the client)
main.py        ASGI entry: `uvicorn server.main:app` (never with --reload)
```

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
  (`render_json`, `stats_json`). A backend crash loses the partial text; the
  turn becomes `interrupted` and retry recovers it.

## Events (`GET /api/runs/{id}/events?after=N`)

Server-sent events, each `{"seq": n, "type": ...}`:

| type | fields | meaning |
|---|---|---|
| `run_started` | `chat_id`, `turn_id` | the agent is built |
| `call_start` | | a model call begins (marks where a retried call is cut back to) |
| `model_retry` | `reason`, `attempt`, `of` | the last model call is discarded and repeated |
| `thinking_delta` | `text` | reasoning |
| `text_delta` | `text` | answer text |
| `tool_start` | `id`, `name`, `args` | a tool call |
| `tool_args_delta` | `id`, `name`, `args` | arguments still arriving |
| `tool_end` | `id`, `name`, `status`, `text` | the result |
| `approval_request` | `id`, `kind` (`install`, `access`, `tool`), `command`, `folder?`, `timeout`, `expires_at` | the tool policy needs the user's answer; the run waits |
| `approval_result` | `id`, `decision` (`allowed`, `denied`, `expired`) | the answer, or the timeout |
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
| `GET /chats`, `POST /chats` | list, create |
| `GET /chats/{id}` | the visible path: each turn with `render`, `stats`, `version`, `versions`, and the active run |
| `PATCH /chats/{id}` | rename |
| `DELETE /chats/{id}` | the chat, its snapshots and its files |
| `GET /chats/{id}/export`, `POST /chats/import` | a chat with every version and its Strands snapshots; an import can be continued |
| `POST /chats/{id}/files`, `GET /chats/{id}/files/{path}` | upload into the chat's workspace; a file as a download (raster images inline) |
| `GET /chats/{id}/workspace` | every file in the workspace, newest first. Outlives edits |
| `POST /chats/{id}/messages` | send `{text, files, refs, thinking}` → `{run, chat}` |
| `POST /turns/{id}/retry` | last turn only → `{run, chat}` |
| `POST /turns/{id}/edit` | `{text, files?, thinking}`, destructive → `{run, chat}` |
| `POST /turns/{id}/select` | `{delta}` → the chat view |
| `GET /runs/{id}`, `GET /runs/{id}/events`, `POST /runs/{id}/cancel` | |
| `POST /runs/{id}/approvals/{approval_id}` | `{allow}`: answer an approval request |
| `GET /pairing`, `POST /pairing/reset` | the browser extension's pairing token (not readable by the extension) |
| `POST /runs/{id}/calls/{call_id}` | the client's result for a `client_call` (a page operation) |
| `GET /profile`, `PUT /profile` | the user's details for fill suggestions (web UI only; the extension cannot read them) |
| `POST /extension/fill` | `{fields, title}` -> `{values, missing}`: one schema-constrained model call; nothing is filled here |
| `POST /extension/table` | `{rows, title, url, format, folder}`: a page's table saved as xlsx/csv, no model |
| `GET /models` | the models in the models folder, which one is running, which is selected |
| `POST /restart`, `GET /restart` | ask `atlas start` to restart llama-server and the backend; how the last restart went |
| `GET /settings`, `PUT /settings` | flat dotted keys; any key can be written (RESTART keys are saved, applied at the next start) |
| `GET /skills`, `POST /skills/install`, `POST /skills/upload`, `PUT /skills/{folder}`, `DELETE /skills/{folder}`, `POST /skills/{folder}/requirements` | |
| `GET /mcp`, `POST /mcp`, `DELETE /mcp/{name}`, `PUT /mcp/{name}`, `POST /mcp/{name}/reconnect`, `PUT /mcp/{name}/tools/{tool}`, `GET /mcp/registry?q=` | a tool's `{mode}` is `on`, `ask` (approve each call) or `off` |

Send, retry and edit return the updated chat view with the run, so the client
replaces the old answer at once instead of waiting for the run to finish.

What the model is told, built per run and never stored as `user_text`:

- **Attachments** (`_agent_text`): names and paths in the `/c/Users/...` form.
  Images and audio are sent as content blocks after the text instead, so a
  voice recording with an empty prompt is a complete message.
- **Passages** (`refs`, from the former preview panel; older turns only), with their file's path,
  ready for `edit_document`.
- **@ mentions** (`_mention_guidance`): `@name` in the text that matches a
  skill, tool or MCP server becomes an explicit instruction. Resolved at run
  time, so a retry or an edit gets the same one; unknown names are ignored.

Each run also records the files it created or changed in the workspace
(`stats.files`), for the download chips.

## Who may call (`security.py`)

Every request: the Host must be 127.0.0.1 or localhost (no DNS rebinding);
an Origin must be the web UI's own (the backend's port, or Vite's), or a
browser extension carrying the pairing token; other sites get 403. A
cross-site request without an Origin (an image, a `no-cors` fetch) needs the
token as `?token=`. Local programs send no Origin and pass.

A message sent with `page: {url, title}` (from the extension) adds the page
tools to that turn; a page tool emits `client_call {id, op, args}` and waits
for the POST back, like an approval.

## The web UI

The backend serves the built UI (`client/dist`) at `/`, with `index.html`
for any page route, so `atlas start` needs no Vite. The build is looked up per
request. `--dev` runs Vite on its own port instead, proxying `/api` here.

## Gotchas

- `created_at` is epoch **milliseconds**.
- `?after=` is the first sequence number the client has **not** seen.
- Never `uvicorn --reload` on Windows: the worker's event loop cannot start
  subprocesses, so every tool that shells out fails with an empty error. The
  backend logs an error at startup if it finds itself on that loop.
