# tests/

Two kinds, kept apart on purpose.

**Offline checks** need no model and run in seconds. CI runs them on every push
(`.github/workflows/checks.yml`), and so should you before a commit:

```
.venv\Scripts\python tests\check.py        # ruff, pyright, pytest, tsc, oxlint
.venv\Scripts\python -m pytest             # the tests only
```

| File | What it pins down |
|---|---|
| `test_policy.py` | the tool policy's steps: approvals, installs, taint, the documents step, path rewrites |
| `test_grid.py` | the permission grid in each mode: place x action, Allow for this chat, Recycle Bin deletes |
| `test_protected.py` | Atlas's own files are refused to every tool, the shell and relative paths included |
| `test_rules.py` | the floor: shell commands refused in every tier, and the rule file checking its own examples |
| `test_shell_classify.py` | shell commands parsed into read, write, delete, install, other |
| `test_installs.py` | install commands recognised by parsing |
| `test_taint.py` | outside content taints the chat, and which MCP servers are trusted |
| `test_limits.py` | run limits: model calls, minutes, repeated calls |
| `test_security.py`, `test_extension_scope.py` | who may call the API, and what the extension's token opens |
| `test_mcp.py`, `test_redact_logs.py` | secrets never reach the UI; MCP tools ask unless set On |
| `test_skills.py` | installing a skill stays inside its download; what a skill needs installed |
| `test_reading.py` | `read_text` and `read_image`: caps, footers, wrong-type errors |
| `test_web.py` | `web_search` / `read_url` against a fake Exa: shaping, labels, refused queries and addresses, errors, asking and taint |
| `test_finding.py` | `find_files` and `list_folder`: ranking, junk folders, content; copy and move never overwrite |
| `test_ingest.py` | the ingest store and `read_pdf` / `read_docx` / `read_xlsx`: OCR, search, ownership, cleanup |
| `test_edit_tools.py` | `create_document`, `edit_docx`, `set_cell`, and tools that arrive with their skill |
| `test_formula_injection.py`, `test_combine_xlsx.py` | spreadsheets: `=` text stays text; the combine script |
| `test_maths.py` | `calculate` and `dates`: results, the forms people write, what is refused |
| `test_chats.py` | the chat tree: send, retry, edit, version switching, crash recovery |
| `test_runs.py`, `test_server_runs.py` | runs: approvals, cancel, replay; however a run ends, its slot is freed |
| `test_uploads.py` | uploads into the workspace, ingest at upload, its progress |
| `test_processes.py` | stopping a service ends everything it started |
| `helpers.py` | shared: a recording approver, an MCP tool, a settings file for a throwaway Atlas |
| `test_suite_graders.py` | the live suite's graders: each passes a right answer and fails a wrong one |
| `client/src/**/*.test.ts(x)` | the web UI (vitest): the store's page calls; tool calls and reasoning drawn collapsed |
| `extension/lib/**/*.test.ts` | the extension (vitest): pairing only with its own Atlas, typed field values never listed |

A test for a known, not yet fixed bug is marked `xfail(strict=True)`, its
reason saying what is wrong. The fix removes the marker; strict
means a fix that lands without removing it fails, so it cannot go unnoticed.

**Live checks** use the real model and need the GPU to themselves (stop any
other Atlas first). Start an Atlas, then point them at it:

```
.venv\Scripts\python tests\live\suite.py --url http://127.0.0.1:8000        # 39 graded tasks, thinking off and on
.venv\Scripts\python tests\live\suite.py --tags files --name files-after-x   # saved as benchmarks/<date>-files-after-x
.venv\Scripts\python tests\live\suite.py --tags docs safety --repeats 3
.venv\Scripts\python tests\live\suite.py --compare model.context_size=16384   # each task with and without
.venv\Scripts\python tests\live\suite.py --list
```

**The suite** (`live/suite.py`, inputs from `live/fixtures.py`) is what
"it still works" and "this is better" mean. Every task has facts planted in its
inputs and a grader that decides by script, never by a model: completeness,
errors (wrong facts, unsafe results) and pass. Tags group them: `docs` (`read`,
`write`, `multi`, `ocr`, `xlsx`, `pdf`, `web`), `tools`, `instructions`, `chat`,
`recovery`, `safety`, `search` (web search through Exa: needs a key, costs a few
cents a run), `files` (`find`, `harm`: harmful requests, graded on why
nothing was harmed: refused, asked and denied, or the model not trying; luck fails). Safety tasks answer approval cards "deny" and check what
survived (a file outside the allowed folders, the pairing token, a .docx the
shell was told to append to); the others answer "allow". `--compare` runs every
task twice, interleaved, without and with the given settings; `--llama` at a
llama-server started with `--metrics` counts model work. Results go to
`benchmarks/<date>-<name>/` (see [benchmarks/README.md](../benchmarks/README.md)):
`summary.txt` by tag and `results.json` are committed; one trace per run goes to
`traces/`, which is not. The graders are themselves tested offline
(`test_suite_graders.py`), each against a right and a wrong answer.

Run the suite more than once before believing a difference: a single run of a
task varies (decisions.md, 2026-11-03 and 2026-11-04).
