# Agent Subsystem: Atlas Execution Runtime & Primitives

The `agent/` directory houses the core intelligence, model adapters, and execution tools for Atlas. Atlas is built as an autonomous execution engine rather than a conversational chatbot—it is explicitly instructed to act, execute, research, and deliver artifacts using its 10 tools.

---

## Directory Architecture

```text
agent/
├── tools/
│   ├── __init__.py          # Exports all 10 unified tools
│   ├── filesystem.py        # Windowed file reading, bounded file creation, surgical edits, directory inspection
│   ├── sandbox.py           # Shell execution, isolated Python execution with uv, clarification gate, finish gate
│   └── web.py               # Live web search and URL content fetching via Exa API
├── __init__.py
├── config.py                # Model gateway, Gemma streaming interceptor, function-call parser, model factory
├── env.example              # Legacy environment variable template (reference only)
└── runtime.py               # AssistantAgent factory, system prompt with grounding rules and temporal awareness
```

---

## Key Modules & Responsibilities

### 1. `agent/config.py` (Model Gateway & Gemma Interceptor)
- **Model Client Factories**:
  - `get_local_model(...)`: Creates a `GemmaOpenAIChatCompletionClient` pointing to `llama-server` (port 8000). Passes `top_p`, `top_k`, slot allocation (`id_slot = hash(chat_id) % 8`), and reasoning budget (`thinking_budget`, `chat_template_kwargs: {"enable_thinking": bool}`).
  - `get_cloud_model(...)`: Creates an `OpenAIChatCompletionClient` or `AnthropicChatCompletionClient` using decrypted cloud credentials from `.storage/settings.json`.
- **Gemma Function-Call Parsing (`extract_gemma_tool_calls`)**:
  - Quantized local Gemma models format tool calls as plain text (e.g. `<|tool_call>call:func{k:<|"|>v<|"|>}<tool_call|>`).
  - `extract_gemma_tool_calls` uses regex and brace-depth counting to extract function names and arguments, cleans `<|"|>` tags, and returns typed `FunctionCall` objects.
- **`GemmaStreamInterceptor`**:
  - AutoGen's `AssistantAgent(model_client_stream=True)` consumes streams from `create_stream()`.
  - `GemmaStreamInterceptor` processes incoming token chunks:
    1. Splits `<think>` and `</think>` tags, tagging reasoning tokens with `<|agent_thought|>`.
    2. Buffers incoming tokens when tool-call signatures (`<|tool_call`, `call:`) are detected to prevent raw syntax from leaking to the frontend SSE stream.
    3. Flushes parsed tool calls wrapped cleanly in `CreateResult(finish_reason="function_calls", content=calls)` so AutoGen executes the tools properly.

### 2. `agent/runtime.py` (System Prompt & Agent Construction)
- **`create_runtime_agent(...)`**: Instantiates a single `AssistantAgent` ("atlas") with all 10 tools registered, `reflect_on_tool_use`, and configurable `max_tool_iterations`.
- **`build_system_message(...)`**: Generates the hardened system prompt containing:
  - Temporal grounding: Injects current real-time clock (`strftime("%A, %B %d, %Y, %H:%M %Z")`).
  - Downloads directory path injection.
  - Mandatory Grounding Rules:
    1. Never use internal memory for real-world/current facts; call `search_web`.
    2. Never output passive Markdown code blocks when asked to make files; execute Python or `create_file`.
    3. Deliverables must be saved to `Downloads` (via `create_file` or `DOWNLOADS_DIR` in Python).
    4. Never simulate tool results.
    5. Call `ask_question` when user intent is ambiguous.

### 3. `agent/tools/` (The 10 Primitives)
Every tool function is wrapped with `@safe_tool_response`, ensuring exceptions are caught and returned as clean strings (`[TOOL_STATUS: ERROR] ...`) instead of crashing AutoGen:

| Tool | File | Responsibility |
|---|---|---|
| `search_web` | `web.py` | Exa API web search with highlights, summaries, and official-source prioritization. Gracefully handles missing API keys. |
| `read_url_content` | `web.py` | Fetches URL text via Exa (capped at 3,000 characters). |
| `run_command` | `sandbox.py` | Shell execution in the session's workspace directory (`cwd=workspace`, 120s timeout, safety regex check against destructive commands). |
| `run_python_code` | `sandbox.py` | Writes `_atlas_task.py` in workspace, injects `DOWNLOADS_DIR` and `WORKSPACE_DIR` as `Path` objects, executes via `python` or `uv run --with <deps>` if dependencies are specified. |
| `view_file` | `filesystem.py` | Windowed reading (default 250 lines) with 1-based line numbers and boundary footers. Bounded to workspace and Downloads. |
| `create_file` | `filesystem.py` | Writes text/code. Relative paths resolve to `Downloads` by default; explicit `workspace/...` paths resolve to workspace. |
| `edit_file` | `filesystem.py` | Surgical string replacement. Enforces exact single-occurrence match (rejects if not found or count > 1). |
| `list_directory` | `filesystem.py` | Lists directory entries. Auto-approved for workspace and Downloads; calls `request_permission` gate if outside. |
| `ask_question` | `sandbox.py` | Suspends execution on `asyncio.Future`, emitting `ask_user` SSE event to prompt the user. |
| `finish` | `sandbox.py` | Mandatory completion gate. Asserts all declared deliverables exist in `Downloads` and are non-empty. |

---

## Rules for AI Agents Modifying `agent/`
1. **Never Raise in Tools**: All tools must return informative error strings upon failure. Uncaught Python exceptions break AutoGen's execution loop.
2. **Path Safety**: Never allow tools to escape `workspace` or `Downloads` without gating through `request_permission`.
3. **Deliverables Contract**: Do not introduce automatic directory-sync hacks. Deliverables must be written to `DOWNLOADS_DIR`; scratchpad files must remain in `WORKSPACE_DIR`.
4. **Tool-Call Syntax**: Do not strip or alter regex token handling in `config.py` without testing against local Gemma's tool-calling template.