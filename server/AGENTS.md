# Server Subsystem: FastAPI Backend & Session Storage

The `server/` directory contains the FastAPI asynchronous backend (listening on port 8001). It orchestrates chat execution turns with AutoGen, manages multi-turn conversation persistence, provides thread-safe cancellation tokens, and hosts dual asynchronous interaction gates.

---

## Directory Architecture

```text
server/
├── app/
│   ├── __init__.py
│   └── main.py                  # FastAPI app factory, CORS config, router registration
├── routers/
│   ├── __init__.py
│   ├── browser.py               # Stub for browser session integration
│   ├── chat.py                  # /api/chat, /stop, /edit, /retry, /permission, /answer
│   ├── memory.py                # /api/memory: persistent facts stored in .storage/memory.json
│   ├── sessions.py              # /api/sessions: list, get, rename, delete chat sessions
│   ├── settings.py              # /api/settings: get/update settings with Windows DPAPI encryption
│   └── skills.py                # /api/skills: local skills listing, install, update, delete
├── services/
│   ├── __init__.py
│   ├── chat_service.py          # Turn runner, SSE generator, interaction gate event draining
│   └── settings_service.py      # DPAPI encryption/decryption, cached Settings instance
├── stores/
│   ├── __init__.py
│   ├── cancellation_registry.py # Thread-safe CancellationToken registry per chat_id
│   ├── interaction_registry.py  # Dual gates (permission: bool, user_input: str) using asyncio.Future
│   └── session_store.py         # Disk-backed persistence under .storage/sessions/{chat_id}/
└── __init__.py
```

---

## Key Modules & Responsibilities

### 1. `server/services/chat_service.py` (Core SSE Turn Runner)
- **Turn Lifecycle**:
  1. Creates or loads session record in `session_store`.
  2. Commits user prompt to `session.json` (unless `skip_user_add=True`).
  3. Binds async SSE emitter: `set_emit_fn(_emit_to_stream)`.
  4. Creates a `CancellationToken` for the turn.
  5. Yields `{"type": "meta", "chat_id": ...}` and `{"type": "status", "status": "running"}`.
  6. Creates and initializes `atlas` agent with local or cloud model.
  7. Restores previous agent memory from `agent_state.json` if continuing a multi-turn conversation.
  8. Runs `atlas.run_stream(task=task, cancellation_token=token)`.
  9. Yields streaming chunks (`type: "chunk"`), thoughts (`type: "thought"`), and tool labels (`type: "status"`).
  10. Drains pending interaction gate events (`permission_request`, `ask_user`) into the SSE stream.
- **Teardown & Persistence Safety**:
  - Catches `BaseException` to intercept both `asyncio.CancelledError` and `GeneratorExit`.
  - In `finally:`, commits the assistant message to `session.json` with `status: "cancelled"` or `"completed"`.
  - Saves serialized agent state (`save_state()`) only if the turn completed without cancellation.
  - Wraps final status SSE yield in a guarded `try ... except (GeneratorExit, RuntimeError)` to prevent runtime errors when client abruptly closes connection.

### 2. `server/stores/session_store.py` (Canonical On-Disk Store)
- Root location: `.storage/sessions/{chat_id}/`.
  - `session.json`: Canonical message history (IDs, roles, content, status, attachments, thoughts, timestamps).
  - `agent_state.json`: Serialized AutoGen agent context.
  - `agent_state_prev.json`: Pre-turn snapshot taken before Turn $N$ runs.
  - `workspace/`: Isolated scratchpad file directory for code execution and file generation.
- **State Rollback & Truncation**:
  - `snapshot_agent_state(chat_id)`: Copies `agent_state.json` $\rightarrow$ `agent_state_prev.json`.
  - `rollback_agent_state(chat_id)`: Restores `agent_state_prev.json` $\rightarrow$ `agent_state.json`.
  - `truncate_to_message(chat_id, message_id, include, clear_state)`: Truncates messages. For retry, `clear_state=True` or `rollback_agent_state` ensures the agent does not retain the failed assistant response in its internal memory.
  - `delete_session(chat_id)`: Cancels active cancellation token before `shutil.rmtree` to prevent Windows file-lock errors.

### 3. `server/stores/interaction_registry.py` (Dual Async Gates)
Provides two mechanisms to suspend agent execution until user interaction resolves:
- **Permission Gate** (`request_permission(tool_name, target, details)`):
  - Suspends on `asyncio.Future[bool]`, emits `type: "permission_request"`.
  - Resolved via `POST /api/chat/{id}/permission` (`resolve_permission(request_id, allow)`).
- **Clarification Gate** (`request_user_input(question)`):
  - Suspends on `asyncio.Future[str]`, emits `type: "ask_user"`.
  - Resolved via `POST /api/chat/{id}/answer` (`resolve_user_input(question_id, answer)`).

### 4. `server/services/settings_service.py` (DPAPI Security)
- Source of truth: `.storage/settings.json`.
- Uses Windows DPAPI (`win32crypt.CryptProtectData` / `CryptUnprotectData`) to encrypt API keys (`ENC:...`).
- Caches decrypted settings in memory (`_settings_cache`) to avoid per-call decryption overhead.

---

## Rules for AI Agents Modifying `server/`
1. **Never Skip Message Persistence**: Assistant messages must be committed to `session.json` even if the client disconnects or generation is aborted. Use `BaseException` and `finally:`.
2. **No Consecutive User Messages**: On retry, always pass `skip_user_add=True` to `process_chat` because the user message is already in `session.json`.
3. **Preserve Turn Context on Retry**: Do not clear `agent_state.json` indiscriminately; use `rollback_agent_state` or ensure earlier turns ($1 \dots N-1$) are preserved.
4. **Endpoint Consistency**: Keep all endpoints prefixed with `/api/...` to align with the Next.js rewrite proxy.