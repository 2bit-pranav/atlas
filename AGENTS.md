# Atlas: Autonomous Execution Engine & Model Harness

Atlas is a single-agent execution harness built around quantized local models (such as Google Gemma running on `llama.cpp` / `llama-server`) and cloud models (Gemini, Claude, GPT). Rather than operating as a conversational web chatbot, Atlas functions as a grounded operating system worker armed with 10 real execution tools, strict anti-hallucination grounding rules, and dual human-in-the-loop interaction gates.

---

## Repository Overview & Layout

```text
atlas/
├── .storage/               # Runtime generated storage (100% git-ignored)
│   ├── memory.json         # Persistent user facts, preferences, domain rules
│   ├── settings.json       # Authoritative configuration with DPAPI-encrypted secrets
│   └── sessions/           # Isolated session stores ({chat_id}/session.json, workspace/)
├── agent/                  # Autonomous agent runtime, tools, prompt, model gateway
├── client/                 # Next.js 16 (App Router) + React 19 + Zustand frontend
├── server/                 # FastAPI backend server (port 8001), session store, SSE engine
├── ext/                    # Portable Windows launch scripts for llama-server
│   ├── start_google_gemma.bat   # Launches llama-server on port 8000 with Google Gemma GGUF
│   └── start_unsloth_gemma.bat  # Launches llama-server on port 8000 with Unsloth Gemma GGUF
├── llm/                    # Local quantized model weights (GGUF) and mmproj files
│   ├── google/             # Official Gemma 4B GGUF + multimodal projection
│   └── unsloth/            # Alternative quantized weights
├── skills/                 # Extensible skills catalog (e.g. skills/pdf/ for PDF workflows)
├── tests/                  # Unit and integration test suites
├── AGENTS.md               # Master repository instructions (this file)
├── requirements.txt        # Python backend & agent dependencies
└── settings.json           # Legacy/fallback settings template (migrated to .storage/ on run)
```

---

## Development Setup Guide (New Machine)

### 1. Prerequisites
- **Python**: 3.10 or 3.11 installed and added to `PATH`.
- **Node.js**: v18.18+ (v20+ recommended) and `npm`.
- **llama-server**: `llama-server.exe` (from `llama.cpp`) available in `PATH` or placed in a known binary path.
- **uv** (optional): Fast Python package runner, used by `run_python_code` when dynamic dependencies are requested.

### 2. Dependency Installation

**Backend Python Virtual Environment**:
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Frontend Node Modules**:
```cmd
cd client
npm install
cd ..
```

### 3. Local Model Placement (`llm/`)
Place your quantized `.gguf` model files and multimodal projection weights (`mmproj`) inside `llm/`:
```text
atlas/llm/
├── google/
│   ├── gemma-4-E2B_q4_0-it.gguf
│   └── gemma-4-E2B-it-mmproj.gguf
```

### 4. Running the Complete System (3-Terminal Startup)

* **Terminal 1: Local LLM Server (Port 8000)**
  ```cmd
  ext\start_google_gemma.bat
  ```
  *Launches `llama-server.exe` on `http://127.0.0.1:8000` with 32k context, Flash Attention (`-fa on`), reasoning auto, and Jinja templates.*

* **Terminal 2: FastAPI Backend Server (Port 8001)**
  ```cmd
  .venv\Scripts\activate
  uvicorn server.app.main:app --port 8001 --reload
  ```
  *Runs API backend on `http://127.0.0.1:8001`.*

* **Terminal 3: Next.js Frontend Client (Port 3000)**
  ```cmd
  cd client
  npm run dev
  ```
  *Access the user interface at `http://localhost:3000`.*

---

## Configuration & Secret Storage

1. **`.storage/settings.json`**:
   The single source of truth for runtime configuration. Managed through the `/settings` page in the UI or directly on disk.
2. **DPAPI Key Protection**:
   On Windows, API keys (Exa, Google, Anthropic, OpenAI) are encrypted via Windows Data Protection API (`win32crypt`) and stored with an `ENC:` prefix. Keys are decrypted only in memory at runtime.
3. **Environment Variables**:
   `agent/.env` is legacy. Settings loaded via `server/services/settings_service.py` govern model execution.

---

## Core Control Pipeline

```
┌────────────────────────┐         HTTP/SSE         ┌────────────────────────┐
│   Next.js Frontend     │ ◄──────────────────────► │    FastAPI Backend     │
│  (React 19 / Zustand)  │  /api/* (Next.js Proxy)  │     (Port 8001)        │
└────────────────────────┘                          └───────────┬────────────┘
                                                                │ Python async
                                                    ┌───────────▼────────────┐
                                                    │   Atlas Agent Runtime  │
                                                    │(AssistantAgent 10 Tools│
                                                    └───────────┬────────────┘
                             ┌──────────────────────────────────┼──────────────────────────────┐
                             ▼                                  ▼                              ▼
                    ┌─────────────────┐                ┌──────────────────┐           ┌──────────────────┐
                    │  Web Primitives │                │  Filesystem Tools│           │ Sandbox Tools    │
                    │- search_web     │                │- view_file       │           │- run_command     │
                    │- read_url_cont. │                │- create_file     │           │- run_python_code │
                    └─────────────────┘                │- edit_file       │           │- ask_question    │
                                                       │- list_directory  │           │- finish          │
                                                       └──────────────────┘           └──────────────────┘
```

### Turn Lifecycle Rules:
1. **Idempotent Status Tracking**: Message states are strictly `"running" | "completed" | "cancelled" | "error"`. Markdown content is never polluted with cancellation strings.
2. **Safe Deliverable Contract**:
   - `WORKSPACE_DIR` is the internal scratchpad for temporary scripts and data.
   - `DOWNLOADS_DIR` is the user-facing destination.
   - `finish(deliverables=[...])` strictly checks and promotes final files into `Downloads`, preventing stale file collisions and workspace pollution.
3. **Tool Call Interception**:
   `GemmaStreamInterceptor` in `agent/config.py` captures Gemma's text-based `<|tool_call>...<tool_call|>` output during streaming, preventing syntax leaks and dispatching typed `CreateResult` instances to AutoGen.
4. **Pre-Turn State Snapshotting**:
   `session_store` preserves `agent_state_prev.json` so that editing or retrying a turn rolls back memory cleanly without losing turns $1 \dots N-1$.

---

## Rules for All AI Agents Working on Atlas
- **Strict Separation of Concerns**: Keep tool execution logic in `agent/`, client presentation in `client/`, and persistence/routing in `server/`.
- **Zero CORS / Direct Port Calls**: Keep frontend calls relative (`/api/...`). Next.js rewrites proxy them to `127.0.0.1:8001`.
- **Always Validate Against the 10 Tools**: Do not invent sub-agents or groups; Atlas operates via a single unified `AssistantAgent`.