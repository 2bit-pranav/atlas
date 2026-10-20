# Roadmap

Ordered so each phase builds on the one before it. Every phase ends with a
gate: what must be true before the next starts. The user tests each phase by
hand; a local benchmark (not in the repo) checks for regressions.

## Phase 0: fixes and a baseline (done, 2026-10-19)

- `web_fetch` summariser cap 600 -> 2048 tokens (it raised `MaxTokensReachedException`).
- MCP tools received `/c/...` paths; they now get `C:/...`.
- Reasoning is passed back to llama.cpp as `reasoning_content`.
- A local benchmark: six tasks (F1 table to xlsx, research, PDF merge with images,
  attachment Q&A, xlsx sum, plain chat), thinking off and on, synthetic fixtures.
- Baseline: 5/12.

## Phase 1: the control layer (done, 2026-10-19)

- One access model: workspace + `access.folders`, ask outside
  (`agent/core/policy.py`). Covers file, document, shell and MCP tools.
- `{atlas:folders}` in an MCP server's args expands to the allowed folders.
- Approvals by kind: install, access, sensitive MCP tool (On / Ask / Off).
- Skill requirements (pip, npm global, npm local) detected, shown and installed
  from the Skills page.
- All pre-call checks in one ordered hook.

Gate: an MCP filesystem server reaches the allowed folders; a path outside asks;
an install runs after Allow; tests pass; benchmark no worse than 5/12.

## Phase 2: answer quality

Installing a search MCP (DuckDuckGo) and the filesystem MCP did most of what
this phase was for: research answers now come from real pages. What is left
is small:

1. **Date and time** (done): today's date in the system prompt, the send time
   at the end of each user message (seen only by the model).
2. **Prefer original sources** (done): one prompt line, plus "give the link".
3. **Relative times in the chat** (done): "2 min ago" under each user message,
   the exact time on hover.
4. **More core skill scripts** (done):
   - pdf: `merge_pdf.py` (files or page ranges, in order), `split_pdf.py`
     (per page or per range), `pdf_to_docx.py` (pdf2docx);
   - docx: `docx_to_pdf.py` (docx2pdf through Word, else LibreOffice, else
     the model is told to read it and `create_document` a PDF);
   - xlsx: `combine_xlsx.py` (workbooks, sheets or CSVs; `--stack`),
     `xlsx_to_csv.py`. No xlsx to PDF: nothing does it without Excel.

Gate: the user's own testing.

On hold, to try only if testing shows a need: `todo_write`, `notebook`, a
subagent research preset (the F1 podium, which needs many pages, is the
likely first case), a script that saves a web page or its tables to a file.

## Phase 3: features

In this order:

1. **Model picker and Restart** (done): pick a model folder in Settings >
   Model, "Restart now" in Settings. Router mode was tried and dropped
   (docs/decisions.md): per-turn switching costs a full load each time on one
   small GPU. Settings reordered: Agent, Skills & MCP, Access, Model first;
   tuning under Advanced.
2. **Unattended runs**: a run queue (a scheduled run must wait behind a chat,
   not be refused), notifications, then schedules, then triggers (file,
   webhook). Webhooks need a local API key first.
3. **Google and Microsoft accounts, through MCP.** Sending or deleting tools
   default to Ask.
4. **Browser extension.** Needs the API key; another origin calling the backend.
5. **CLI and release**, together at the end:
   - a TUI (Textual): startup screen with per-process status and logs, and a
     chat screen over the same API;
   - onboarding: dependencies, first-run settings with defaults, pick or
     download a model;
   - Hugging Face downloads into `llm/` and a model picker;
   - packaging for a GitHub release with a CLI install.

On hold: cloud models (a separate Strands model class per provider; the
llama.cpp patches do not apply).

## Backlog

- Default MCP servers offered like the bundled skills (filesystem, search).
- A real sandbox for skill scripts (the shell path check guards mistakes only).
