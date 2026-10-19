# Roadmap

Ordered so each phase builds on the one before it. Every phase ends with a
gate: what must be true before the next starts. Quality changes are measured
with `python tests/bench.py` against the last saved run (`.data/bench/`).

## Phase 0: fixes and a baseline (done, 2026-10-19)

- `web_fetch` summariser cap 600 -> 2048 tokens (it raised `MaxTokensReachedException`).
- MCP tools received `/c/...` paths; they now get `C:/...`.
- Reasoning is passed back to llama.cpp as `reasoning_content`.
- `tests/bench.py`: six tasks (F1 table to xlsx, research, PDF merge with images,
  attachment Q&A, xlsx sum, plain chat), thinking off and on, synthetic fixtures.
- Baseline: 5/12.

## Phase 1: the control layer (done, 2026-10-19)

- One access model: workspace + `access.folders`, ask outside
  (`agent/core/policy.py`). Covers file, document, shell and MCP tools.
- `{atlas:folders}` in an MCP server's args expands to the allowed folders.
- Approvals by kind: install, access, sensitive MCP tool (On / Ask / Off).
- Skill requirements (pip, npm global, npm local) detected, shown and installed
  from the Skills page.
- All pre-call checks in one ordered hook; offline tests in `tests/test_policy.py`.

Gate: an MCP filesystem server reaches the allowed folders; a path outside asks;
an install runs after Allow; tests pass; benchmark no worse than 5/12.

## Phase 2: answer quality

One change at a time, each benchmarked; keep only what helps.

1. **System prompt**: today's date and time; gather -> checklist -> produce ->
   verify; "never claim what a tool result contradicts".
2. **Search**: the user's search MCP (SearXNG), so URLs are found, not guessed.
3. **`todo_write`** (harness `Todos` plugin): a plan re-shown every turn.
4. **`notebook`** (Strands vended tool): a scratchpad for gathered data;
   `create_document` can render from a notebook; a page-break marker.
5. **Subagent research preset**: delegate anything that is more than one tool
   call to a child with its own notebook.
6. **More core skill scripts**:
   - pdf: merge / combine with page ranges, split;
   - docx: convert to pdf, common edits;
   - xlsx: convert to pdf/csv, common operations.

Gate: benchmark clearly above 5/12, with no single case regressing.

## Phase 3: features

In this order:

1. Hugging Face models: download, a router and a model picker.
2. Cloud models.
3. A CLI for chatting.
4. Triggers.
5. Schedules and notifications.
6. A browser extension.
7. Google and Microsoft accounts, through MCP.

## Backlog

- Default MCP servers offered like the bundled skills (filesystem, search).
- A real sandbox for skill scripts (the shell path check guards mistakes only).
