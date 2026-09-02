# Atlas: A Model Harness for Reliable AI Capability

## Project Vision

**Atlas is a harness around language models** — both local (Llama.cpp) and cloud-based (Google Gemini, OpenAI) — designed to dramatically improve their practical usability, reliability, and success rates when operating as autonomous agents.

Rather than relying on a model's raw training knowledge and simulated capabilities, Atlas provides:
- **Grounded execution**: Real tools for web research, file operations, and browser automation
- **Proper delegation patterns**: Clear rules for when to call specialists vs. hallucinate
- **Output validation**: Auditing agents that verify completeness and reject placeholders
- **Session continuity**: Multi-turn conversation management with persistent agent state
- **Streaming transparency**: Real-time visibility into agent reasoning and tool execution

The result: local models behave far more reliably than base models, while cloud models are cost-optimized through proper grounding rules and tool delegation.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Next.js Client (React 19, TypeScript)                 │
│  - Chat UI with real-time SSE streaming                │
│  - Session management (sidebar)                         │
│  - File attachment support                             │
│  - Markdown rendering with syntax highlighting         │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/SSE
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI Server (async/uvicorn)                        │
│  - Session persistence (ChatSessionManager)             │
│  - File handling and validation                         │
│  - Streaming response orchestration                     │
│  - Terminal event multiplexing (for tool output)       │
└──────────────────────┬──────────────────────────────────┘
                       │ Python async
┌──────────────────────▼──────────────────────────────────┐
│  Atlas Core Orchestrator (AutoGen-based)               │
│  - Main AssistantAgent ("atlas")                       │
│  - Tool delegation & grounding rules                   │
│  - Specialized agent team composition                  │
│  - Reflection & iteration (max 5 tool cycles)          │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
    ┌─────────┐  ┌──────────┐  ┌─────────────┐
    │   Web   │  │  File    │  │  Browser    │
    │ Research│  │Operations│  │ Automation  │
    │ Team    │  │ Team     │  │ Agent       │
    └────┬────┘  └────┬─────┘  └──────┬──────┘
         │             │               │
         └─────────────┴───────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   ┌─────────┐  ┌──────────┐  ┌─────────────┐
   │ Ollama  │  │ LM Studio│  │ Google API  │
   │ (Local) │  │ (Local)  │  │ / OpenAI    │
   │ 4-7B   │  │ 7B-13B  │  │ (Cloud)     │
   └─────────┘  └──────────┘  └─────────────┘
```

---

## Core Components

### 1. **Atlas Orchestrator** (`agent/agent.py`)

The primary AssistantAgent that routes requests to specialists.

**Key Features:**
- **Grounding rules system**: Explicit instructions to prefer web research before browser automation, and to never simulate operations
- **Temporal awareness**: Current date/time injected into system message for correct date filtering
- **Tool iteration**: Up to 5 reflective tool cycles before terminating
- **Three specialized tools**: Web research, file operations, browser automation

**System Message Philosophy:**
```
"NEVER use internal training memory for real-world facts, dates, sports champions..."
"FOR FACTUAL/RECENT QUERY: Call WebResearchTeam FIRST"
"FOR LIVE BROWSER TASKS: Call BrowserAgent FIRST with a valid URL"
"FOR FILE CREATION: Call FileAgent"
"NEVER claim, simulate, or pretend to perform operations yourself"
```

This prevents the cardinal sin of local models: hallucinating or falling back on training data when they should delegate.

---

### 2. **WebResearchTeam** (`agent/web_agent/agent.py`)

A **RoundRobinGroupChat** with two agents:

**Scraper Agent:**
- Executes `web_search()` and `web_fetch()` tools
- Formulates effective search queries (not blindly searching entire user prompt)
- Respects temporal context: "last 5 F1 seasons" knows the current date
- Returns concise evidence with source URLs

**Auditor Agent:**
- **Critical validation role**: Checks if collected evidence is sufficient
- Does NOT fact-check using its own knowledge (anti-hallucination measure)
- Verifies completeness against explicit user requirements:
  - Requested item counts complete?
  - Missing fields or dates?
  - All names, numbers, attributes present?
- Terminates with `DATA_COMPLETE` or specifies `DATA_INCOMPLETE` with exact missing info

**Termination:** Stops when auditor says `DATA_COMPLETE` OR after 12 turns (safety limit)

**Why this pattern?**
Local models tend to stop searching too early or overfit to their training data. The auditor forces completeness before proceeding.

---

### 3. **FileAgent Team** (`agent/file_agent/agent.py`)

A **RoundRobinGroupChat** with executor + auditor pattern:

**File Executor Agent:**
- Tools: `save_text_file`, `create_pdf_document`, `create_docx_document`, `create_excel_spreadsheet`, `verify_file`
- **Anti-placeholder rule**: "NEVER use placeholders, `[Insert...]`, `[TODO]`, `[TBD]`, `...` in tool arguments"
- Writes FULL text content into tool parameters (no lazy shortcuts)
- Automatically targets user's `Downloads` folder
- Always verifies output file exists and has non-zero size

**File Auditor Agent:**
- Inspects executor's tool invocation arguments for placeholder abuse
- Confirms correct format tool was called
- Verifies `verify_file` was invoked with `VERIFY_SUCCESS` response
- Returns `FILE_TASK_COMPLETE` or `FILE_TASK_INCOMPLETE` with reason

**Why this pattern?**
Large output operations (PDFs, DOCX) on local models are prone to lazy shortcuts. The auditor enforces rigor.

---

### 4. **BrowserAgent** (`agent/browser_agent/agent.py` + `tools.py`)

A specialized agent for live web automation.

**Key capability**: Invokes `run_browser_use_task` which:
- Launches headless Chromium (via Playwright)
- Uses browser-use library to interpret natural language tasks
- Extracts information from interactive pages (booking portals, dynamic sites)
- Returns structured `BrowserUseRuntimeResult`

**System Message:**
```
"You are BrowserAgent, a specialized browser automation specialist."
"Your sole function is to invoke run_browser_use_task"
"Do not simulate browser actions without calling the tool"
"Return final_answer and relevant details back to Atlas"
```

**Design insight:**
- Single-responsibility: One specialized agent, one tool
- No model hallucination about "what a page looks like"
- Real-time CDP streaming for transparency
- Windows-specific: Uses ProactorEventLoop for subprocess creation without deadlock

---

### 5. **Model Configuration** (`agent/config.py`)

Dual-mode model support:

**Local Models (Ollama/LM Studio):**
- Endpoint: `http://127.0.0.1:8000/v1` (OpenAI-compatible)
- Default: `gemma-4-E2B_q4_0-it.gguf` (quantized 4-bit, ~2GB)
- Token encoding: Registered with tiktoken as `cl100k_base` alias

**Cloud Models (Google Gemini, OpenAI):**
- Google: `gemini-3.5-flash-lite` via `https://generativelanguage.googleapis.com/v1beta/openai/`
- Fallback: OpenAI-compatible endpoints
- Requires `CLOUD_API_KEY` environment variable

**Model Info Capability Matrix:**
```python
vision=True,                # Can process images
function_calling=True,      # Can invoke tools
structured_output=True,     # Can return JSON schemas
json_output=True,          # Can parse JSON responses
```

**Token counting workaround:**
Gemma 4B produces non-standard tool argument strings. Custom parser handles:
```python
parse_gemma_args_string()  # Converts <|"...|> to JSON-safe format
strip_thinking_tags()      # Removes <think> blocks for output clarity
```

---

### 6. **FastAPI Server** (`server/app/main.py`, `routers/chat.py`)

**Session Management** (`server/managers/session_manager.py`):
- In-memory `ChatSessionManager` singleton
- Per-session: `id`, `title`, `messages`, `agent_state`, `created_at`, `updated_at`
- Methods: `create_session()`, `add_message()`, `set_agent_state()`, `delete_session()`

**Chat Orchestration** (`server/services/chat_service.py`):
- `validate_path()`: Validates file attachments
- `extract_file_content()`: Handles images, PDFs, DOCX, Excel, text
- `build_task_payload()`: Constructs `MultiModalMessage` for multi-file inputs
- `process_chat()`: Main async generator that:
  - Creates/retrieves session
  - Records user message with attachment metadata
  - Sets up terminal callback for browser-use logging
  - Creates atlas agent with model client
  - Restores agent state (for multi-turn conversations)
  - Streams atlas output via dual-queue architecture:
    - `msg_queue`: Atlas streaming chunks (ModelClientStreamingChunkEvent, ThoughtEvent, TaskResult)
    - `terminal_queue`: Browser tool step logs (non-blocking drain every 0.1s)
  - Records assistant message + agent state

**Why dual queues?**
Local models with browser tasks: without dual-queue polling, terminal logs batch until browser tool returns (could be 30+ seconds). Dual queues enable real-time streaming of step logs.

**SSE Streaming Response:**
```python
async def event_generator():
    async for item in ChatService.process_chat(...):
        yield f"data: {json.dumps(item)}\n\n"
```

Events sent:
- `{"type": "meta", "chat_id": "..."}`
- `{"type": "chunk", "content": "..."}`
- `{"type": "thought", "content": "<reasoning>"}`
- `{"type": "terminal", "content": "[Step 5] Goal: ..."}`

---

### 7. **Next.js Client** (`client/`)

**Tech Stack:**
- React 19 + TypeScript
- Next.js 16.2 (app router)
- Zustand for state (chat-store, ui-store, text-input-store)
- Tailwind CSS + shadcn/ui components
- React Markdown (with GFM syntax highlighting)
- Base UI for advanced components

**Key Pages:**
- `app/page.tsx`: Main chat interface (SSE stream subscriber)
- `components/layout/app-layout.tsx`: Sidebar with session list
- `components/markdown-renderer.tsx`: Renders assistant thoughts/chunks with code highlighting
- `components/text-input/text-input.tsx`: Multi-attachment file upload + chat input

**Session Flow:**
1. User types prompt + attaches files
2. Client POST to `/api/chat` (FormData with files)
3. Server streams SSE events back
4. Client renders real-time: thoughts, code chunks, terminal steps
5. On completion, session saved to sidebar

---

## Design Patterns & Principles

### 1. **Explicit Grounding Over Training Knowledge**

```python
# BAD (base model behavior):
User: "Who won the 2025 Grammy Awards?"
Model: *simulates from training data* "Taylor Swift won 3 awards..."

# GOOD (Atlas behavior):
User: "Who won the 2025 Grammy Awards?"
Atlas: "I'll search for this information..."
  -> WebResearchTeam.web_search("2025 Grammy Awards winners")
  -> Returns live data from Grammy.com
  -> Returns accurate, verifiable answer with source
```

**Grounding rules in system message prevent models from reverting to training data.**

### 2. **Delegation Pattern**

```python
# Models can't truly do these things:
# ❌ "Search the web" (can't make real HTTP requests)
# ❌ "Open a browser" (no subprocess access)
# ❌ "Create a file" (OS-dependent I/O)

# Models CAN do these things:
# ✅ Call tools with natural language -> Tools execute -> Return results
# ✅ Reason about results and iterate
# ✅ Delegate to specialists when scope is outside expertise
```

**Anti-pattern rule:** System message explicitly forbids simulation.

### 3. **Auditing for Quality Assurance**

All major operations have auditors:

| Operation | Executor | Auditor | Pass Criteria |
|-----------|----------|---------|---------------|
| Web Research | Scraper Agent | Auditor Agent | `DATA_COMPLETE` |
| File Creation | File Executor | File Auditor | `FILE_TASK_COMPLETE` + no placeholders |
| Browser Task | Browser Agent | (Built-in reflection) | `final_answer` + `steps` > 0 |

**Why auditors?**
- Prevent premature termination (models stop searching too early)
- Reject lazy outputs (placeholders, `[TODO]`)
- Force verification (file exists, has content)
- Local models especially prone to these shortcuts

### 4. **Temporal Grounding**

```python
current_datetime = datetime.now().astimezone().strftime("%A, %B %d, %Y, %H:%M %Z")

system_message = f"""
Current date and time: {current_datetime}

Relative to {current_datetime}, ensure queries for "last N years" include 
the most recent completed events up to today.
"""
```

Prevents models from returning outdated "current" information.

### 5. **Multi-Turn State Persistence**

```python
# On first message:
agent_state = await atlas.save_state()
chat_session_manager.set_agent_state(chat_id, agent_state)

# On subsequent messages:
prev_state = chat_session_manager.get_agent_state(chat_id)
await atlas.load_state(prev_state)
```

**Benefit:** Agent remembers previous research, file context, and tool results across turns without re-explaining everything.

### 6. **Reflection Before Iteration**

```python
atlas = AssistantAgent(
    ...,
    reflect_on_tool_use=True,      # Think about tool results
    max_tool_iterations=5,          # Safety limit
)
```

After each tool call, model re-evaluates: "Is this sufficient? Should I call another tool or respond?"

---

## Data Flow: A Complete Chat Turn

### **Setup Phase**
1. **Client** POSTs to `/api/chat` with prompt + files
2. **Server** receives request in `chat_endpoint()`
3. Files written to `uploads/{chat_id}/`
4. Session created via `chat_session_manager.create_session(chat_id)`

### **Orchestration Phase**
1. **ChatService** extracts file content (images, PDFs, text)
2. Builds `MultiModalMessage` (text + images combined)
3. Creates/loads `atlas` agent with model client
4. Loads previous agent state (if multi-turn)
5. Sets up terminal callback for browser-use logging

### **Execution Phase**
1. **Atlas** receives task + multimodal context
2. Reads system message grounding rules
3. Decides which specialist to call:
   - Web research? → `WebResearchTeam`
   - File generation? → `FileAgent`
   - Browser automation? → `BrowserAgent`
4. Each specialist team runs its own loop (search → audit, execute → audit, etc.)
5. Results bubble back to atlas for synthesis

### **Streaming Phase**
1. **ChatService.process_chat()** streams via dual-queue:
   - Main queue: Model chunks/thoughts
   - Terminal queue: Browser tool step logs
2. Every 0.1s, drain any pending terminal logs (non-blocking)
3. Yield events as JSON to SSE stream
4. Client receives real-time updates

### **Persistence Phase**
1. After all tools complete:
   - Save accumulated response to `session["messages"]`
   - Save agent state: `await atlas.save_state()` → saved to manager
2. Next turn loads this state automatically
3. Browser session (if used) stored in `BrowserSessionManager` for HITL coordination

---

## Reliability Improvements Over Base Models

| Challenge | Base Model | Atlas |
|-----------|-----------|-------|
| Outdated facts | Uses training data (often 1-2 years old) | Web search fetches live data |
| Interactive tasks | Simulates (browser doesn't actually open) | Real Playwright + browser-use automation |
| File I/O | Claims success without verifying | File agent creates + auditor verifies file exists |
| Long outputs | Uses placeholders, `[...]`, stops early | Auditor rejects placeholders, forces completeness |
| Multi-turn context | Loses details across turns | Agent state persisted, fully restored |
| Local model knowledge gaps | Hallucinates or refuses | Delegates to web team instead |
| User confusion | Hard to know what model actually did | Terminal step logs + thought streaming |

---

## Deployment Modes

### **Local-First Development**
```bash
# Terminal 1: Start Ollama/LM Studio
ollama serve  # or LM Studio GUI

# Terminal 2: Start FastAPI server
uvicorn server.app.main:app --port 8001 --reload

# Terminal 3: Start Next.js client
cd client && npm run dev

# Access: http://localhost:3000
```

**Model:** Gemma 4B quantized (`~2GB RAM, runs on CPU`)

### **Cloud Hybrid**
```env
CLOUD_API_KEY=sk-...
CLOUD_MODEL_NAME=gemini-3.5-flash-lite
USE_CLOUD=true  # In frontend form
```

**Trade-off:** Higher accuracy/speed, lower latency, but costs per query.

### **Production**
- Deploy FastAPI to Cloud Run / Railway / Heroku
- Deploy Next.js to Vercel
- Use cloud model by default (cost-optimized)
- Fallback to local model for privacy-sensitive tasks

---

## Future Extensibility

### **Additional Agents**
```python
create_pdf_extraction_agent()    # OCR + table detection
create_video_analysis_agent()    # Frame extraction + scene understanding
create_code_execution_agent()    # Sandboxed Python interpreter
create_database_agent()          # SQL query generator + executor
```

### **Enhanced Tool Auditing**
- Semantic similarity checks for plagiarism detection
- Structured data validation (schemas, constraints)
- Security scanning (no credentials in outputs)
- Compliance checks (GDPR, PII redaction)

### **Persistent Storage**
```python
# Replace in-memory manager with:
class PostgresSessionManager(ChatSessionManager):
    def __init__(self, db_url):
        self.db = AsyncPgDatabase(db_url)
    
    async def create_session(self, chat_id):
        return await self.db.sessions.insert({...})
```

### **Model Fine-Tuning**
Use conversation logs to fine-tune local models:
- Train on successful tool-calling patterns
- Learn grounding rules via LoRA
- Improve multi-turn coherence

---

## Summary

**Atlas transforms a base model into a reliable agent** by:

1. **Enforcing delegation** over hallucination
2. **Providing real tools** for web, files, and browsers
3. **Validating outputs** via auditor agents
4. **Maintaining context** across multi-turn conversations
5. **Streaming transparency** into reasoning and tool execution
6. **Supporting local models** without sacrificing capability

The result: A 4-7B local model with proper grounding behaves more reliably than a base model 10x larger, while maintaining privacy and reducing inference costs.
