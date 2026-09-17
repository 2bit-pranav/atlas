# Atlas: A Model Harness for Reliable AI Capability

## Setup & Configuration Guide (New PC Deployment)

To configure and run this project on a new PC, follow this setup guide.

### 1. Prerequisites

* **Python**: Version 3.10 or 3.11 installed and added to PATH.
* **Node.js**: Version 18+ and npm installed.
* **llama-server** (llama.cpp): `llama-server.exe` executable available on PATH or placed in a known binary folder.
* **uv** (optional): Required only for `run_python_code` with dynamic `dependencies`.

---

### 2. Dependency Installation

1. **Python Virtual Environment**:
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. **Frontend Client Dependencies**:
```cmd
cd client
npm install
cd ..
```

---

### 3. Local LLM Model Setup (`/llm`)

Place your quantized `.gguf` model files and multimodal projection weights (`mmproj`) inside the `llm` folder at the root of the repository:

```text
atlas/
├── llm/
│   ├── google/
│   │   ├── gemma-4-E2B_q4_0-it.gguf
│   │   └── mmproj-model-f16.gguf
│   └── unsloth/
│       ├── model.gguf
│       └── mmproj.gguf
```

---

### 4. Portable Startup Scripts (`/ext`)

The startup scripts inside the `ext/` folder launch `llama-server` on **port 8000**. To ensure portability across different PCs without hardcoded absolute paths, use relative path resolution via `%~dp0`:

#### `ext/start_google_gemma.bat`

```bat
@echo off
set ROOT_DIR=%~dp0..
llama-server.exe -m "%ROOT_DIR%\llm\google\gemma-4-E2B_q4_0-it.gguf" --mmproj "%ROOT_DIR%\llm\google\mmproj-model-f16.gguf" --port 8000 -c 32768 -fa
```

#### `ext/start_unsloth_gemma.bat`

```bat
@echo off
set ROOT_DIR=%~dp0..
llama-server.exe -m "%ROOT_DIR%\llm\unsloth\gemma-4-E2B_q4_0-it.gguf" --mmproj "%ROOT_DIR%\llm\unsloth\mmproj-model-f16.gguf" --port 8000 -c 32768 -fa
```

---

### 5. Environment Variables Configuration (`agent/.env`)

Copy `agent/env.example` to `agent/.env` and update the values:

```env
# Local model server (llama-server on port 8000)
LOCAL_MODEL_NAME=gemma-4-E2B_q4_0-it.gguf
LOCAL_BASE_URL=http://127.0.0.1:8000/v1/

# Cloud Model Credentials (Optional / Fallback)
CLOUD_MODEL_NAME=gemini-3.5-flash-lite
CLOUD_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
CLOUD_API_KEY=your-cloud-api-key

# Web Research API
EXA_API_KEY=your-exa-api-key
```

> **Note:** API keys are stored encrypted via Windows DPAPI in `settings.json`. The `.env` file is only used as a reference; runtime settings are loaded from `settings.json` through the Settings service.

---

### 6. Running the Application (3-Terminal Launch)

Open **3 separate terminals** in the project root:

* **Terminal 1: Local LLM Server**
```cmd
ext\start_google_gemma.bat
```
*(Starts `llama-server` listening on `http://127.0.0.1:8000`)*

* **Terminal 2: FastAPI Backend Server**
```cmd
.venv\Scripts\activate
uvicorn server.app.main:app --port 8001 --reload
```
*(Runs backend API on `http://localhost:8001`. Uses port 8001 to avoid conflicting with port 8000 used by `llama-server`)*

* **Terminal 3: Next.js Frontend Client**
```cmd
cd client
npm run dev
```
*(Launches user interface on `http://localhost:3000`)*

---

## Project Vision

**Atlas is a production-grade single-agent execution harness** around language models — both local (llama-server / llama.cpp running quantized models like Gemma 4B) and cloud-based (Google Gemini, OpenAI, Anthropic) — designed for reliability and grounded execution over raw model knowledge.

Rather than relying on a model's raw training knowledge and simulated capabilities, Atlas provides:
- **Grounded execution**: 10 real tools for web research, file operations, code execution, and human-in-the-loop clarification
- **Proper grounding rules**: Explicit system instructions for when to search, when to execute, and when to ask
- **Output validation**: `finish` tool programmatically asserts files exist before concluding
- **Session continuity**: Multi-turn conversation management with persistent agent state
- **Streaming transparency**: Real-time visibility into agent tool calls and reasoning
- **Dual async interaction gates**: `ask_question` (user clarification) and `list_directory` (permission) suspend execution via `asyncio.Future` and resume on SSE-delivered user responses

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Next.js Client (React 19, TypeScript)                  │
│  - Chat UI with real-time SSE streaming                 │
│  - Session management (sidebar)                         │
│  - File attachment support                              │
│  - Permission gate UI (permission_request events)       │
│  - User-input gate UI (ask_user events)                 │
│  - Markdown rendering with syntax highlighting          │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/SSE
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI Server (async/uvicorn)                         │
│  - Disk-backed SessionStore (.storage/sessions/)        │
│  - File upload handling & workspace isolation           │
│  - Streaming SSE response orchestration                 │
│  - Interaction gate endpoints (/permission, /answer)    │
└──────────────────────┬──────────────────────────────────┘
                       │ Python async
┌──────────────────────▼──────────────────────────────────┐
│  Atlas Agent Runtime (AutoGen AssistantAgent)           │
│  - Single agent, 10 tools, hardened system prompt       │
│  - Grounding rules: search before generating facts      │
│  - Anti-simulation: run_python_code > Markdown blocks   │
│  - Deliverables: write to DOWNLOADS_DIR, call finish    │
│  - Reflection & iteration (configurable max iterations) │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────────┐
        │              │                  │
        ▼              ▼                  ▼
   ┌─────────┐  ┌────────────┐  ┌────────────────┐
   │   Web   │  │ Filesystem │  │    Sandbox     │
   │  Tools  │  │   Tools    │  │    Tools       │
   │search_  │  │ view_file  │  │ run_command    │
   │  web    │  │create_file │  │run_python_code │
   │read_url │  │ edit_file  │  │ ask_question   │
   │_content │  │list_direct.│  │    finish      │
   └────┬────┘  └────┬───────┘  └───────┬────────┘
        │             │                  │
        └─────────────┴──────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   ┌─────────┐  ┌──────────┐  ┌─────────────┐
   │ llama-  │  │ LM Studio│  │ Google API  │
   │ server  │  │(Local)   │  │ / OpenAI /  │
   │ (Local) │  │          │  │ Anthropic   │
   └─────────┘  └──────────┘  └─────────────┘
```

---

## Directory Structure

```text
atlas/
├── .storage/
│   └── sessions/
│       └── {chat_id}/
│           ├── session.json         # Canonical chat message history
│           ├── agent_state.json     # AutoGen serialized context (save_state / load_state)
│           └── workspace/           # Isolated scratchpad sandbox per session
│
├── agent/
│   ├── __init__.py
│   ├── config.py                    # ModelGateway: Gemma interceptor, slot pinning, cloud SDK factory
│   ├── runtime.py                   # create_runtime_agent: assembles 10 primitives, builds hardened prompt
│   └── tools/
│       ├── __init__.py              # Exports all 10 tools
│       ├── sandbox.py               # run_command, run_python_code, ask_question, finish
│       ├── filesystem.py            # view_file, create_file, edit_file, list_directory
│       └── web.py                   # search_web, read_url_content (Exa SDK)
│
├── client/                          # Next.js Frontend
│   ├── app/
│   │   ├── api/
│   │   │   ├── memory/route.ts
│   │   │   └── settings/route.ts
│   │   ├── browser-sessions/page.tsx
│   │   ├── integrations/page.tsx
│   │   ├── memory/page.tsx
│   │   ├── settings/page.tsx
│   │   ├── skills/page.tsx
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx                 # Fixed status visibility; live tool labels always shown
│   ├── components/
│   │   ├── layout/
│   │   │   ├── app-layout.tsx
│   │   │   ├── sidebar.tsx
│   │   │   ├── sidebar-item.tsx
│   │   │   └── terminal-panel.tsx
│   │   ├── text-input/
│   │   │   ├── attachment-chip.tsx
│   │   │   ├── plus-menu.tsx
│   │   │   ├── profile-dropdown.tsx
│   │   │   ├── text-area.tsx
│   │   │   └── text-input.tsx       # Dual Send / Stop button (<Square /> on isLoading)
│   │   ├── ui/
│   │   ├── markdown-renderer.tsx
│   │   └── theme-provider.tsx
│   ├── lib/
│   │   └── utils.ts
│   ├── stores/
│   │   ├── chat-store.ts            # Typed turn runner (send, stop, edit, retry)
│   │   ├── session-store.ts         # Decoupled session listing & CRUD store
│   │   ├── text-input-store.ts
│   │   └── ui-store.ts
│   ├── package.json
│   └── tsconfig.json
│
├── ext/
│   ├── start_google_gemma.bat       # Updated launcher (-fa on, -c 32768)
│   └── start_unsloth_gemma.bat
│
├── server/
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py                  # Mounts active routers and stub endpoints
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py                  # POST /api/chat, /stop, /edit, /retry, /permission, /answer
│   │   ├── sessions.py              # GET, PATCH, DELETE /api/sessions
│   │   ├── settings.py              # GET, POST /settings (DPAPI encryption)
│   │   ├── browser.py               # Stub returning {"sessions": []}
│   │   └── skills.py                # Stub returning {"skills": []}
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat_service.py          # Turn runner with gate-event draining & SSE streaming
│   │   └── settings_service.py      # In-memory settings caching & DPAPI decryption
│   ├── stores/
│   │   ├── __init__.py              # Re-exports all store symbols
│   │   ├── session_store.py         # Disk-backed SessionStore (.storage/sessions/{chat_id}/)
│   │   ├── cancellation_registry.py # Thread-safe CancellationToken registry
│   │   └── interaction_registry.py  # Dual gates: permission (bool) & clarification (str)
│   └── __init__.py
│
├── skills/                          # Static asset directory
│   └── pdf/
│
├── AGENTS.md
├── requirements.txt
└── settings.json                    # Authoritative configuration (DPAPI-encrypted secrets)
```

---

## Complete Tool Catalog

Every tool is decorated with `@safe_tool_response` — guaranteeing it returns a string and never raises an unhandled exception into AutoGen.

| # | Tool Name | Module | Signature | Responsibility |
|---|-----------|--------|-----------|----------------|
| **1** | `search_web` | `agent.tools.web` | `search_web(query: str) -> str` | Searches the live web via Exa API. Returns numbered title, URL, summary, and highlights. |
| **2** | `read_url_content` | `agent.tools.web` | `read_url_content(url: str) -> str` | Extracts clean text from a target URL (capped at 3,000 chars). |
| **3** | `run_command` | `agent.tools.sandbox` | `run_command(command: str) -> str` | Executes a shell command in the session workspace. 120s timeout; safety-checked against destructive patterns. |
| **4** | `run_python_code` | `agent.tools.sandbox` | `run_python_code(code: str, dependencies: Optional[list[str]] = None) -> str` | Executes Python in the workspace. Pre-injects `DOWNLOADS_DIR` and `WORKSPACE_DIR` as `Path` objects. Uses `uv run` when dependencies are specified. |
| **5** | `view_file` | `agent.tools.filesystem` | `view_file(file_path: str, start_line: Optional[int], end_line: Optional[int]) -> str` | Windowed read (250 lines default) with 1-based line numbers and boundary header/footer markers. |
| **6** | `create_file` | `agent.tools.filesystem` | `create_file(file_path: str, content: str) -> str` | Writes text or code to a path in the workspace or Downloads. Returns line and byte counts. |
| **7** | `edit_file` | `agent.tools.filesystem` | `edit_file(file_path: str, old_string: str, new_string: str) -> str` | Surgical single-occurrence string replacement. Rejects if `old_string` is absent or ambiguous (>1 match). |
| **8** | `list_directory` | `agent.tools.filesystem` | `list_directory(directory_path: str = ".") -> str` | Lists entries with types and sizes. Workspace/Downloads auto-approved; host paths trigger permission gate. |
| **9** | `ask_question` | `agent.tools.sandbox` | `ask_question(question: str) -> str` | Human-in-the-loop gate. Suspends on `asyncio.Future[str]`, emits `ask_user` SSE event, returns `[USER_RESPONSE]: {answer}` when resolved. |
| **10** | `finish` | `agent.tools.sandbox` | `finish(summary: str, files_created: list[str]) -> str` | Mandatory completion gate. Asserts all listed files exist on disk with size > 0. Returns `[FINISH_SUCCESS]` or `[FINISH_REJECTED]`. |

---

## Core Components

### 1. **Atlas Agent Runtime** (`agent/runtime.py`)

The single `AssistantAgent` ("atlas") that handles all requests directly using its tool suite.

**Key Features:**
- All 10 tools registered directly on the agent
- Hardened system prompt with grounding rules and anti-simulation instructions
- Temporal awareness: current date/time injected into system message
- Configurable reflection and max tool iterations from `settings.json`

**System Prompt Philosophy:**
```
"You are ATLAS, an autonomous execution engine directly wired to live operating system and network tools."
"NEVER use internal training memory for real-world facts... Always call search_web first."
"When a task requires creating a file... call run_python_code or create_file — never output raw Markdown code blocks."
"Write all deliverable files to DOWNLOADS_DIR. Confirm every deliverable by calling finish."
"When the user's intent is ambiguous, call ask_question before proceeding."
```

This prevents local models from hallucinating results, outputting passive Markdown code, or assuming facts from stale training data.

---

### 2. **Tool Suite** (`agent/tools/`)

#### Web Tools (`web.py`)
- **`search_web`**: Exa API search with configurable `max_results`, highlights, and summaries.
- **`read_url_content`**: Exa content fetch, capped at 3,000 characters of clean text.

#### Sandbox Tools (`sandbox.py`)
- **`run_command`**: Shell execution in workspace with forbidden-pattern safety check.
- **`run_python_code`**: Python execution with `DOWNLOADS_DIR` and `WORKSPACE_DIR` pre-injected. Supports dynamic deps via `uv run`. No magic deliverable copying — the model writes directly to `DOWNLOADS_DIR`.
- **`ask_question`**: Async gate — calls `request_user_input()`, emits `ask_user` SSE, suspends until user submits answer.
- **`finish`**: Verifies all files in `files_created` exist and are non-empty on disk before concluding.

#### Filesystem Tools (`filesystem.py`)
- **`view_file`**: Line-numbered windowed read (250 lines default). Header: `--- START OF FILE WINDOW: {name} (Lines {start}-{end} of {total}) ---`. Footer shows remaining line count.
- **`create_file`**: Writes to workspace or Downloads with parent directory creation.
- **`edit_file`**: Single-occurrence surgical replacement — rejects 0 or >1 matches.
- **`list_directory`**: Auto-approves workspace/Downloads paths; calls `request_permission()` for external host paths.

---

### 3. **Dual Async Interaction Gates** (`server/stores/interaction_registry.py`)

Two mechanical suspension mechanisms backed by `asyncio.Future` and `ContextVar`-bound SSE emitters:

**Permission Gate** (binary):
```python
# Tool calls this:
allowed = await request_permission("list_directory", str(path), {...})
# → Emits: {"type": "permission_request", "request_id": "perm_xxx", "tool": ..., "target": ...}
# → Suspends on Future[bool]
# Frontend POSTs to /api/chat/{id}/permission → resolve_permission(request_id, allow)
```

**Clarification Gate** (string):
```python
# Tool calls this:
answer = await request_user_input(question)
# → Emits: {"type": "ask_user", "question_id": "q_xxx", "question": ...}
# → Suspends on Future[str]
# Frontend POSTs to /api/chat/{id}/answer → resolve_user_input(question_id, answer)
```

Both gates are ContextVar-scoped per request and cleaned up in the `finally` block of `chat_service.py`.

---

### 4. **Chat Service & Event Streaming** (`server/services/chat_service.py`)

The core SSE turn runner:

1. Binds `set_emit_fn(_emit_to_stream)` so interaction gates can inject events into the SSE stream.
2. Streams `ToolCallRequestEvent` messages as `type: "status"` with human-readable labels immediately.
3. Drains any pending gate events (`while emitted_events`) on each loop iteration.
4. Streams `ModelClientStreamingChunkEvent` as `type: "chunk"` and `ThoughtEvent` as `type: "thought"`.
5. Falls back to `TextMessage` content if no chunks were streamed.
6. Calls `clear_emit_fn()` in `finally` to clean up per-request context.

**SSE Event Types:**
| Event Type | Payload | Description |
|---|---|---|
| `meta` | `{"chat_id": "..."}` | Session ID confirmation |
| `status` | `{"status": "running", "label": "Searching the web..."}` | Live tool activity label |
| `chunk` | `{"content": "..."}` | Streaming response text |
| `thought` | `{"content": "..."}` | Streaming reasoning/thinking content |
| `permission_request` | `{"request_id": "...", "tool": "...", "target": "..."}` | Binary permission gate |
| `ask_user` | `{"question_id": "...", "question": "..."}` | String clarification gate |
| `error` | `{"detail": "..."}` | Unhandled exception detail |

---

### 5. **FastAPI Endpoints** (`server/routers/chat.py`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Main chat endpoint (multipart/form-data with file uploads) |
| `POST` | `/api/chat/{chat_id}/stop` | Cancel active generation via `CancellationToken` |
| `POST` | `/api/chat/{chat_id}/messages/{id}/edit` | Truncate history at message, re-run with new prompt |
| `POST` | `/api/chat/{chat_id}/messages/{id}/retry` | Re-run previous user prompt for an assistant message |
| `POST` | `/api/chat/{chat_id}/permission` | Resolve a pending `list_directory` permission gate |
| `POST` | `/api/chat/{chat_id}/answer` | Resolve a pending `ask_question` clarification gate |

---

### 6. **Settings Service** (`server/services/settings_service.py`)

- **In-memory caching**: `get_effective_settings()` returns a cached `Settings` object; only re-loads and decrypts from disk on startup or after `save_settings()` invalidates the cache.
- **DPAPI encryption**: Cloud API key and Exa API key are stored `ENC:`-prefixed in `settings.json` and decrypted only in memory.
- **Local-mode optimization**: Cache means DPAPI decryption is paid once per process lifetime, not once per tool call.

---

### 7. **Session Store** (`server/stores/session_store.py`)

Disk-backed per-session state under `.storage/sessions/{chat_id}/`:
- `session.json` — chat message history with IDs, roles, attachments, thoughts
- `agent_state.json` — AutoGen serialized agent context (`save_state` / `load_state`)
- `workspace/` — isolated file sandbox for the session

---

### 8. **Next.js Client** (`client/`)

**Tech Stack:** React 19, TypeScript, Next.js, Zustand, Tailwind CSS, shadcn/ui, React Markdown.

**Key Fix — Status Display (`client/app/page.tsx`):**

Previously, `currentStatus` (live tool labels like `Searching the web...`) was buried inside a `thought ?` branch, meaning it only rendered when the model had already emitted reasoning tokens. This caused the UI to freeze on `"Thinking..."` during tool execution.

**Fixed:** Collapsed to a single span that always shows the current status:
```tsx
<span className="text-muted text-xs animate-pulse">
    {currentStatus || (thought ? "Reasoning..." : "Thinking...")}
</span>
```

Now live tool labels appear immediately regardless of whether the model has started generating text.

---

## Design Patterns & Principles

### 1. **Single Agent, 10 Primitives**

The previous multi-agent pattern (WebResearchTeam, FileAgent, BrowserAgent as separate AutoGen group chats) has been replaced with a single `AssistantAgent` armed with all 10 tools. This eliminates:
- Orchestration overhead between group chats
- Auditor-agent round-trip latency
- Complex termination condition management

The model delegates via tool calls, not sub-agent spawning.

### 2. **Explicit Grounding Over Training Knowledge**

```python
# BAD (base model behavior):
User: "Who won the 2025 Grammy Awards?"
Model: *returns training data* "Taylor Swift won..."

# GOOD (Atlas behavior):
User: "Who won the 2025 Grammy Awards?"
Atlas: calls search_web("2025 Grammy Awards winners")
     → Returns live data with source URLs
     → Returns accurate, verifiable answer
```

### 3. **No Magic Deliverable Copying**

Old behavior: `_sync_deliverables()` scanned the workspace for specific file extensions after each Python run and auto-copied them to Downloads.

New behavior: The model is instructed to write deliverables directly to `DOWNLOADS_DIR` (pre-injected as a `Path` variable). `finish()` verifies files exist. This makes the flow transparent and auditable.

### 4. **Surgical File Editing**

`edit_file` enforces uniqueness: `old_string` must appear exactly once in the file. This prevents accidental mass-replacement while still enabling precise, model-driven code edits.

### 5. **Line-Numbered Windowed File Reading**

`view_file` defaults to 250 lines per call with explicit boundary markers:
```
--- START OF FILE WINDOW: main.py (Lines 1-250 of 892) ---
    1 | import asyncio
    2 | from pathlib import Path
  ...
--- END OF FILE WINDOW (642 lines below). Call view_file(..., start_line=251) to inspect further. ---
```

This replaces the previous arbitrary 25,000-character slice which provided no positional context to the model.

### 6. **Temporal Grounding**

```python
current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")
# Injected into system message every turn
```

Prevents models from returning stale "current" information.

### 7. **Multi-Turn State Persistence**

```python
# On each turn end:
agent_state = await atlas.save_state()
session_store.set_agent_state(chat_id, agent_state)

# On next turn start:
prev_state = session_store.get_agent_state(chat_id)
await atlas.load_state(prev_state)
```

Agent remembers previous tool results and context across turns.

---

## Data Flow: A Complete Chat Turn

### Setup Phase
1. Client POSTs to `/api/chat` with prompt + files (multipart/form-data).
2. Server saves uploads to `workspace/{chat_id}/uploads/`.
3. Session created / retrieved via `session_store`.

### Execution Phase
1. `ChatService.process_chat()` binds `set_emit_fn` for gate event injection.
2. `set_active_workspace()` pins the session workspace via `ContextVar`.
3. Atlas agent loaded with model client and previous agent state (if multi-turn).
4. `atlas.run_stream(task=task)` begins.

### Streaming Phase
1. `ToolCallRequestEvent` → `type: "status"` with live tool label.
2. Gate events (`permission_request`, `ask_user`) drained from `emitted_events` buffer each loop iteration.
3. `ModelClientStreamingChunkEvent` → `type: "chunk"` or `type: "thought"`.
4. `TaskResult` fallback → `type: "chunk"` from last `TextMessage`.

### Persistence Phase
1. Full assistant response saved to `session["messages"]`.
2. Agent state serialized and stored: `await atlas.save_state()`.
3. `clear_emit_fn()` called in `finally`.
4. `type: "completed"` or `type: "stopped"` sent as final event.

---

## Reliability Improvements

| Challenge | Base Model | Atlas |
|-----------|-----------|-------|
| Outdated facts | Uses training data (1-2 years old) | `search_web` fetches live data |
| File creation | Outputs Markdown code blocks, no files made | `run_python_code` / `create_file` with `DOWNLOADS_DIR` |
| Large file reading | Character-sliced with no positional context | `view_file` with 250-line windows and line numbers |
| Surgical code edits | Rewrites entire files | `edit_file` enforces single-occurrence replacement |
| Long output shortcuts | Placeholders, `[...]`, early termination | `finish` rejects if files missing or empty |
| Multi-turn context | Loses details across turns | Agent state persisted and fully restored |
| Ambiguous intent | Guesses or hallucinates | `ask_question` gate suspends for clarification |
| Directory access | No controlled access | `list_directory` gate for host paths |
| Slow key decryption | DPAPI called per tool invocation | Settings cached in memory; decrypted once |
| Frozen "Thinking..." UI | Status hidden behind thought-branch check | Single span always showing `currentStatus` |

---

## Deployment Modes

### **Local-First Development**
```cmd
# Terminal 1
ext\start_google_gemma.bat

# Terminal 2
.venv\Scripts\activate
uvicorn server.app.main:app --port 8001 --reload

# Terminal 3
cd client && npm run dev
```
**Model:** Gemma 4B quantized (`~2GB RAM, runs on CPU`)

### **Cloud Hybrid**
Configure `settings.json` via the Settings UI or directly:
```json
{
  "model": {
    "cloud": {
      "provider": "google",
      "name": "gemini-2.0-flash",
      "api_key": "ENC:..."
    }
  }
}
```
Set `use_cloud: true` in the frontend form field.

### **Production**
- Deploy FastAPI to Cloud Run / Railway / Heroku
- Deploy Next.js to Vercel
- Use cloud model by default; local model for privacy-sensitive tasks

---

## Future Extensibility

### **Additional Tools**
```python
# Easy to add to agent/tools/ and register in runtime.py:
run_sql_query(query: str)           # Sandboxed SQL executor
extract_pdf_text(file_path: str)    # OCR + table detection
take_screenshot(url: str)           # Headless Playwright screenshot
```

### **Persistent Storage**
```python
# Replace disk-backed session_store with:
class PostgresSessionStore(SessionStore):
    async def get_session(self, chat_id: str): ...
    async def add_message(self, ...): ...
```

### **Tool-Level Auditing**
- Semantic similarity checks for plagiarism detection
- Structured data validation (schemas, constraints)
- PII redaction before writing files

### **Model Fine-Tuning**
Use session logs to fine-tune local models on successful tool-calling patterns via LoRA.

---

## Summary

**Atlas transforms a base model into a reliable autonomous agent** by:

1. **Providing 10 real OS and network tools** — no simulation, no hallucination
2. **Enforcing grounding rules** through the system prompt
3. **Line-numbered windowed file I/O** instead of character slicing
4. **Surgical single-occurrence file editing** with ambiguity rejection
5. **Dual async interaction gates** for permission and clarification
6. **In-memory settings caching** for fast TTFT on repeated requests
7. **Mandatory `finish` gate** that verifies deliverables before concluding
8. **Real-time SSE streaming** of tool labels, gate events, and reasoning
9. **Multi-turn state persistence** across conversation turns
10. **Supporting local 4B quantized models** without sacrificing reliability
