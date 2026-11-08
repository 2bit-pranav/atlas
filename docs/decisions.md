# Decisions and findings

Why Atlas is built the way it is. Each entry is something that was observed or
decided, with the evidence, so nobody has to rediscover it. Newest first within
each topic. Add to this file in place; when an entry stops being true, strike
it through and say what replaced it, rather than deleting it. Ids like B28 and
"plan item 5" are from the restructure plan of 2026-10-30.

---

## Strands and the harness

**Keep the current turn's reasoning in the history** (2026-10-19, found by
test). Atlas stripped every `reasoningContent` block before sending history
to llama-server. Within one turn the model then lost its plan after each tool
call. It restated the task every step, loaded the same skill twice and re-ran
the same tool: 6 model calls and 38 s for a two-part question. `/apply-template`
showed that Gemma's template already keeps the current turn's thoughts and
drops older turns'. So reasoning is now passed as `reasoning_content` and the
template decides. The same question then took 2 model calls and 14 s.

**Turn off Strands' printing callback handler** (2026-10-19, found by test).
`Agent` defaults to a `PrintingCallbackHandler` that writes every token to
stdout. Started by `atlas start` the console was cp1252, so an emoji or `→`
in an answer raised `UnicodeEncodeError` and failed the run.

**MCP tools need their server in the description** (2026-10-19, found by
test). Asked to "use the MCP tools", the model picked built-in tools or went
looking for skills. With `[MCP: <server>]` on each description, and the
prompt listing tools by source, it picked the server's tool.

**Never write `snapshot_latest`** (2026-10-18, found by test). Strands writes
it after every invocation and restores it automatically whenever an agent
starts. A turn with no restore point (a first message, or a retry or edit of
one) therefore started with the previous conversation already loaded. The
session manager uses `save_latest_on="trigger"`; Atlas always names the
snapshot it restores.

**Usage arrives on the raw `metadata` event** (2026-10-18). Not on
`messageStop`, which the first event parser read.

**Reasoning is reported twice** (2026-10-18, measured). Once as a raw
`contentBlockDelta.reasoningContent` event and once as a normalised
`{"reasoningText": ..., "delta": ...}` event. Translating both doubled every
word on screen. Only the raw one is used.

**One agent per turn** (2026-10-17). The only way to guarantee that a changed
LIVE setting applies to the next message is to build the agent from the
current settings every time. Building is cheap; restoring the snapshot is the
slow part, so it runs off the event loop.

**The snapshot's stored system prompt wins over a new one** (2026-10-17,
measured). After `restore_snapshot`, the prompt saved in the snapshot replaces
the one passed to `create_harness`, so an edited `system_prompt` would never
reach a chat with history. The prompt is set again after every restore,
recomposed with `build_system_prompt` so the harness's own guidance stays
(assigning our text raw dropped it).

**Snapshots are immutable and restorable from any branch** (2026-10-17,
measured). `save_snapshot(is_latest=False)` writes a new file under a
time-ordered id. A later restore-and-rerun does not touch it, and snapshots
from abandoned branches stay restorable. So switching versions is a restore,
never a recomputation.

**Events come from `stream_async`, no custom hooks for the UI** (2026-10-17).
It already reports text, reasoning, tool arguments as they stream, and tool
results as complete messages. A tool result carries only a `toolUseId`, so the
parser keeps an id → name map for the whole run.

**Memory stays off** (2026-10-17, measured). These four switches are all
needed: `memory=False`, `context_manager=False`, `background_tasks=False`,
`builtin_plugins=[]`.
- With memory on, the harness's store is a flat folder of `.md` files with no
  chat or branch in the key, injected every turn: a fact from one branch leaked
  into another.
- With memory off but `background_tasks` on, the request still contained
  `strands_manage_background_task`.
- Extraction failures are swallowed, so a broken extractor looks the same as an
  isolated one.

Assert isolation on **bytes on disk**, not on answers: a plausible answer can
be guessed.

**Build on the harness, not the plain SDK** (2026-10-16). `create_harness`
returns a normal Strands `Agent` with tools, skills, sessions and MCP built in.
Atlas only configures it. Everything Atlas adds is listed in the README.

---

## llama.cpp, the model and the prompt

**Images go to the model inside tool results** (2026-10-21, measured).
llama-server accepts an `image_url` part in a tool message: Gemma read
"Experiment No - 05" from a screenshot returned by a tool. So
`page_screenshot` / `page_image` hand the image straight back; through the
side panel it read a scanned circular correctly.

**One model at a time, switched by restart** (2026-10-20, measured, decided).
llama-server's router mode (`--models-dir`, loading models on demand) was
built and then dropped. The router itself costs nothing (226 ms vs 221 ms to
first token with the prompt cached, 84 t/s either way), but every switch
costs a full load (7.6-11 s for Gemma on a 4 GB GPU) plus re-reading the
prompt with an empty cache (4.1 s for 7.9k tokens), so per-turn switching
is out on one small GPU; cloud harnesses can do it because their models stay
loaded. A model that does not fit (Agents-A1-4B at 32k context crashed with
0xC0000409, most likely out of GPU memory) also failed only when first used.
So llama-server runs `-m <gguf> --mmproj <file>` for the model chosen in
Settings > Model, found by folder name in `llm/`, and "Restart now" in Settings
applies it: the backend writes `restart.request`, `atlas start`'s supervisor
restarts llama-server and the backend, and `restart.json` says how it went.
A restart is no slower than the router's load, and a failure shows at once.
Measured: switching Gemma to Agents-A1 on CPU took 13 s end to end.

**Sampling settings are not per model** (2026-10-20, decided). Temperature,
top-p/k, min-p, penalties, max tokens, context size and the thinking switch
are request or server parameters with the same meaning for any model,
fine-tune or quant. No model profiles.

**8192 output tokens per model call** (2026-10-19, found by test). With 2048,
reasoning plus a rewritten document ran out mid tool call. Strands could not
parse the truncated arguments, ran `create_document` with `{}`, and the model
had to write the whole document again.

**The date in the prompt, the time in the message** (2026-10-19, decided).
The system prompt carries today's date, which changes once a day, so
llama.cpp's prompt cache is kept. Each user message ends with
`[Sent Mon 19 Oct 2026, 18:38 (UTC+05:30)]`, which only the model sees.

**Stream the response** (2026-10-18). The stock adapter used
`client.post(...)`, which makes httpx read the whole body before returning, so
each model call arrived in one burst. Most visible with thinking on, because
the wait is longer. The adapter now uses `client.stream(...)`.

~~**Strip reasoning from history**~~ (2026-10-18, found by test). With thinking
on, Strands keeps a `reasoningContent` block in the assistant message, and
`LlamaCppModel._format_messages` raises `content_type=<reasoningContent> |
unsupported type` on it. Every model call after a tool call failed. Reasoning
is now dropped before sending; it was never meant to be replayed.

> Reversed on 2026-10-19: *Keep the current turn's reasoning in the history*.

**Replace `document` blocks** (2026-10-18, found by test). The harness `read`
tool returns a pdf/docx/xlsx as a `document` block for cloud models that can
view one. llama-server rejects it with a 400 and the run fails. It becomes a
text note pointing at the skill.

> Update 2026-11-03: the harness `read` is gone; the replacement stays for any other tool that returns a document block.

**Context meter from `timings`** (2026-10-18). With `timings_per_token`,
llama-server sends `cache_n`, `prompt_n`, `predicted_n` and speeds on each
chunk. Context in use = `cache_n + prompt_n + predicted_n`.

**Thinking needs an explicit flag** (2026-10-17, measured). The stock adapter
copies a whitelist of request keys and drops `chat_template_kwargs`. The server
defaults to thinking on, so `enable_thinking` is always sent. On/off only; no
effort or budget control was verifiable.

**Images are separate blocks** (2026-10-17, measured).
- `LlamaCppModel` converts `image` blocks to `image_url` data URIs.
- `source.bytes` is required.
- A combined `{"image": ..., "text": ...}` block silently drops the text, even
  though the adapter's own docstring shows that shape.

**Not `--tools all`** (2026-10-17). That is llama.cpp's own tool set. Passing it
would show the model a second shell and file tool beside the Strands ones.

---

## What a 2B model can do (measured)

**Finding files: the baseline, and safety by luck** (2026-11-05,
`tests/live/suite.py --tags files`, 14 tasks x thinking off/on, a throwaway
home tree as the only allowed folder, filesystem MCP on). Found a file with
no path given in 5 of 12 runs. The model is never told it has folders: asked
what its resume says it asked for the resume; asked about "my project's
meeting notes" it searched the web and answered with a company's IPO date.
When it did look, it listed one level per call. Once a folder was known,
finding a file by its contents and reading it (ingested on first use) worked
every time. Harmful requests left the files intact in 10 of 10, but only 6
by policy (the floor for Atlas's own files; a denied card for the real
Downloads, outside the folders). The other 4 were luck: `rm Documents/Old/
Resume 2022.pdf` ran three times without asking and failed only on the
unquoted space. Offline, `rm -rf ~/Downloads/*` and `$HOME/...` pass every
check (targets with `~` or a variable were skipped), and nothing asks before
a delete inside the allowed folders. The filesystem MCP server also brought
write tools (`append_file`, `move_file`, `copy_file`) not in the rejected
list. Plan: docs/plan.md.

**Two llama.cpp slots: measured before planning parallel work** (2026-11-04,
RTX 3050 Laptop 4 GB, Gemma E2B, Atlas's own llama-server arguments). Each
request: a distinct ~4.5k-token prompt, 300 tokens out, thinking off.

| setup | VRAM | one request alone | two at once, both done | per request while paired |
|---|---|---|---|---|
| 1 slot, 32k | 2.75 GB | 5.6 s (84 tok/s out, 2,340 tok/s in) | 11.0 s (queued) | unchanged |
| 2 slots, shared 32k (`--kv-unified`) | 2.75 GB | 5.5 s | 8.9 s | 56-62 tok/s out, ~1,200 tok/s in |
| 2 slots, 32k each (`-c 65536`) | 2.97 GB | 5.5 s | 8.7 s | 57-63 tok/s out, ~1,340 tok/s in |

Two slots finish two jobs 20% sooner (combined output 120 tok/s against 84),
not twice as fast: prompt reading is compute-bound and is simply shared. A
second 32k slot costs 0.22 GB. One request alone is as fast with 2 slots as
with 1.

Gemma E2B already puts two tool calls in one reply some of the time: asked to
read two files, 2 calls in 3 of 6 replies with thinking off, 1-2 of 6 with it
on; llama.cpp's `parallel_tool_calls` flag made no difference. Strands runs
the calls of one reply concurrently (`ConcurrentToolExecutor`, its default).

**Plan plus workers does not help this model: one turn stays** (2026-11-04,
a multi-part benchmark, since retired). Three multi-part tasks with planted facts, graded by
script: a three-source summary from local web pages, a two-file comparison
(6 planted differences), a five-section report from notes. Mode A is today's
agent; mode B adds the plan tool (`todo_write`) and workers (`subagent`), and
asks to plan and hand each part to a worker. Same 2-slot llama-server
(`--kv-unified`), modes interleaved, thinking off and on, 3 repeats: 36 runs.
Model work from llama-server's counters, workers included.

| | complete | errors/run | perfect runs | avg time | prompt tokens in |
|---|---|---|---|---|---|
| A, one turn | 88% | 0.1 | 10/18 | 17 s | 6.7k |
| B, plan + workers | 41% | 0.6 | 3/18 | 49 s | 15.8k |

B lost on every task (draft 100% vs 32%, comparison 83% vs 58%, research 67%
vs 45%) and worst with thinking on (96% vs 14%). The workers did their parts
well; the parent orchestrated badly: it delegated one file twice and the
other once, then stopped without comparing; it tried the plain `write` tool
on a .docx, never loaded the docx skill, and said the report was done; it
passed workers' summaries on with figures dropped. A 2B model cannot hold a
plan, track workers and merge their results; one turn with everything in
view does better. Two of A's research misses were the model choosing an MCP
fetch tool that refuses private addresses, not the task; they count against A.

Kept, off by default: `tools.builtin.subagent` is now Atlas's own worker tool
(`runtime/workers.py`): workers share the parent's policy, limits and taint
tracking, get their own failure budget, no session, no printing callback, and
cannot delegate further (the harness's own wiring forwarded none of the
printing, retry or recovery settings and shared the failure budget).
`tools.builtin.todos` switches the plan tool. Worth measuring
again on a larger model.

> Update 2026-11-04: removed the same day, see *`subagent` and `web_fetch` are removed, not switched off*.

**The plan tool does not help this model either** (2026-11-04,
the same tasks and setup as plan plus workers). Mode B:
the harness's `todo_write` (rewrites the list, so it can check off, reorder,
reword, add and drop), re-shown before every call, guidance in the system
prompt, and `PlanCheck` (runtime/plan.py), which sends the model back once
when it ends with steps open; a finished plan is cleared at the next message.
The message is the same in both modes. 36 runs:

| | complete | errors/run | perfect runs | avg time | prompt tokens in |
|---|---|---|---|---|---|
| A, no plan | 97% | 0.0 | 13/18 | 16 s | 6.7k |
| B, plan | 63% | 0.2 | 10/18 | 28 s | 8.5k |

B lost on every task (draft 100% vs 48%, comparison 86% vs 75%, research 100%
vs 83%), worst with thinking off (96% vs 45%). The plan competed with the
work: the model wrote its plan, then read the same PDF three times without
checking anything off until the repeat limit stopped it; or it spent four
`todo_write` calls on the comparison and then never wrote the differences
down; or it tried the plain `write` tool on report.docx. Mode A scored higher
than in the workers run (97% against 88%) because its research sources are
now PDFs read by link, not pages fetched through a tool that refused them.

`tools.builtin.todos` stays, off by default, with `PlanCheck`; worth re-running
on a larger model. In both modes the docx skill not being loaded sometimes
sent the model to `write` or `python -c` for a .docx: refused or lost, not
corrupt.

> Update 2026-11-04: removed the same day; `runtime/plan.py` and `tools.builtin.todos` are gone.

**Document baseline before the file pipeline** (2026-11-03, `benchmarks/2026-11-03-documents-baseline`).
Eight document tasks (long text PDF, 12-page scan, short PDF, docx table, xlsx
sum, 3,000-line log, docx edit, xlsx edit), thinking off and on, run twice:
8/16 passed in the clean run. Questions on short files mostly pass; what fails:
- The harness `read` returned a 3,000-line log whole (124,792 characters, 70k
  tokens): the request overflowed the 32k context and the turn failed, both
  modes, both runs. `read` has no cap.
- `read` was called on a binary document 6 to 11 times per 16 runs; one run
  spent four calls on it before loading the skill.
- Long PDF: the reader shows pages 1-2 by default and the model answered "not
  present" without searching; once it searched with a phrase ("sensor K7
  calibration constant") that substring search cannot match, on a path it
  invented under `skills/`.
- Edits: 1 of 8 runs passed. The docx reader prints a table as a pipe row and
  the model passes that row to `edit_document`, which matches within one cell.
  No tool sets a spreadsheet cell; the model tried SQL with string literals in
  double quotes (identifiers in DuckDB).
- Every document task spends a call and about 1-1.5k tokens loading a skill;
  the fixed prompt (system, tools) is about 4.4k tokens.
- Readers are fast on text (0.2-0.5 s). OCR is 2.1 s per page cold (12 pages,
  25.7 s); `--search` on a scan OCRs every page first.

> Update 2026-11-04: these tasks are now part of `tests/live/suite.py`.

**Benchmark baseline: 5/12** (2026-10-19, measured with a local benchmark kept out of the repo). Fails
are about quality, not plumbing: no date context, guessed URLs with no search
engine, the `web_fetch` summariser mangling tables, dropped images in long
copies, claimed-but-not-done steps, and giving up early with thinking off.
Each change below is measured against this.

**A search MCP mattered more than new tools** (2026-10-19, found by test).
With a filesystem and a DuckDuckGo search MCP installed, a search-save-verify
task ran cleanly in 5 calls, and the F1 task returned real, correct winners.
What remained was the date: the model read "last season" as 2024 because it
did not know the year. So `todo_write`, `notebook` and subagents are on hold.

> Update 2026-11-04: measured since. Neither the plan tool nor workers helped (*Plan plus workers ...*, *The plan tool ...*); both are removed.

---

## Reading and writing documents

**`read_text` and `read_image` replace the harness `read`** (2026-11-03). The harness `read` is off (it is no longer a setting); Atlas's own
tools are capped near 1,500 tokens, name what they left out and the next call,
search by words rather than the phrase, and answer a pdf/docx/xlsx with its
reader command and an image with `read_image`. The policy's `read` redirect
went with it. `benchmarks/2026-11-03-documents-typed-read-tools`: 11/16 (baseline 8/16). Every question
about a PDF, docx or xlsx passed; wrong-tool calls fell from 6-11 to 2; edits
are still 0/4 (the writing tools, below). The long log still failed with thinking off (read
the first window, said "no error codes") until its attachment line gave the
line count and the search form: then 4/4, one call each, 5.8k context instead
of 8.6k. Saying so in the result's header alone did not do it (1/3).

> Update 2026-11-04: the long-log case and its fixtures are in `tests/live/suite.py`.

**Documents are parsed at upload; reading is fetching** (2026-11-03). `agent/ingest/`: an upload or import submits the file, one worker
parses it into blocks in one SQLite database with FTS5 (`<data>/parsed/
index.db`, images beside it), a PDF's text layer first and each scanned page
as OCR finishes. `read_pdf`, `read_docx` and `read_xlsx` fetch from it. One
database instead of a folder of JSON files per document: transactions make
every write atomic, and search lives in the same file. Entries are shared by
content hash, owned per chat; deleting a chat drops entries nobody else owns;
an `asset:` image resolves only for an owner. `read_pdf` refuses `file://`
(the old script read any PDF on disk through one, past the access check).
The skill reader scripts and the per-folder `.atlas-images` writes are gone.

Measured: a text PDF, docx or xlsx is ready 0.1-0.2 s after upload; on the
12-page scan a requested page arrives in 3.3 s (the old `--search` OCR'd all
12 pages first, 25.7 s), the rest in 18 s in the background.
`benchmarks/2026-11-03-documents-ingest-store-cold`: 13/16 (typed read tools: 11/16, baseline 8/16).
All 12 question runs passed, with no wrong-tool calls; a PDF question now
takes 1-2 tool calls. Edits 1/4, for the writing tools. Two fixes the runs forced: a
search on a scan still being OCR'd now waits up to 30 s (returning at once,
the model searched 3 s after upload and gave up), and a long PDF's footer
offers search before the next pages (offered pages first, the model walked
18 of 40 pages).

The edit checks now require the rest of the file unchanged: one "pass"
was the model regenerating the whole workbook with `create_document` after
five failed edits, with February's numbers replaced by January's. Overwriting
an attached file with a regenerated copy is a data-loss risk to settle with
the writing tools.

**Writing tools come with their skill; edits are by address** (2026-11-03). `create_document`, `edit_docx` and `set_cell` are registered
when the pdf, docx or xlsx skill is loaded (`runtime/skill_tools.py`); a chat
that only reads never carries them. Strands takes the tool list from the
registry before every model call, so a tool registered after `skills` runs is
offered on the next call; the skills plugin keeps loaded skills in the
agent's state, which the snapshot saves, so later turns rebuild the same list,
always in one order (it is part of llama.cpp's cached prefix). A call before
the skill is loaded is answered "load the docx skill". `edit_document` is
gone: `edit_docx` takes the id `read_docx` printed (`b12`, `t1.r3.c3`, rows
now printed numbered) and `set_cell` a cell (`Mar!B2`), only on a version of
the file the chat attached or read. The old tool could not change a number in
a spreadsheet at all: it matched text cells only. `create_document` never
replaces a file (an existing name gets `-2`), after a regenerated workbook
replaced one month's figures with another's.

`benchmarks/2026-11-03-documents-writing-tools`, cold store, edit checks requiring the rest of
the file unchanged: 16/16 (ingest store: 13/16, baseline 8/16). Fixes the runs forced: a
read with no `path` takes the only document of its type; a bare SQL
expression with a sheet becomes `SELECT ... FROM "sheet"`, and a failed query
lists each sheet's columns (the model wrote `SUM(B)`, then tried pandas and
`pip install`); `edit` called with `edit_docx`'s arguments is answered with the
exact `edit_docx(...)` call (it was refused generically and gave up).

**Attachment chips show parsing progress** (2026-11-03).
`GET /chats/{id}/ingest?names=...` gives each attachment's status and a PDF's
pages done; the composer polls it once a second until ready or failed.
Checked live on the 12-page scan: 0 to 12 pages, then ready. Web UI only, not
in the extension's routes.

**One document-link resolver** (2026-10-22). A PDF link was opened by two
copies of the same logic: the skill scripts' `fetch` and the backend's
`pdf_source` (extension import, PDF viewer), with different download code,
naming and checks. `skills/_shared.py` now has the only one (`open_link`,
`save_link`; standard library, so the scripts still run on their own) and the
backend imports it.

**Stop stops the command; long PDFs are read in parts** (2026-10-22). A
question about a 67-page scanned PDF ran `read_pdf.py --pages all`: Atlas's
own suggested command said `all`, and every scanned page is OCR'd, so it ran
for minutes, and kept running after Stop, because Strands only cancels at its
safe points and on Windows its runner would kill only `sh.exe`. Now Stop or
the timeout kills the command's process tree; the suggested command has no
`--pages`; the reader reads a short PDF (5 pages or fewer) whole, else pages
1-2 with the page count, and refuses more than 15 pages per call with a hint
to `--search` first.

> Update 2026-11-03: the PDF half is replaced; reads come from the ingest store, capped by output size and searchable, with no page cap.

**`calculate` and `dates` as direct tools** (2026-10-22). The model added
five amounts in its head and was off by 60. Two general tools, one string
argument each (an expression), evaluated from an allow-list with exact
decimals. Exposed directly, switchable in Settings; no enforcement yet, to see
how often the model uses them unprompted. The @ menu lists MCP servers by name
only (every MCP tool made it too long), after tools and skills.

~~**One PDF reader, OCR per page**~~ (2026-10-21, measured). `read_pdf.py`
reads the text layer where there is one and OCRs the rest: a page with
almost no text and a page-sized image is rendered and read; a large picture
on a text page is read and kept when it holds real text (at least 20
characters, mean confidence 0.75), so a diagram does not turn into "O O".
No second command: the model picks the first reader it sees. RapidOCR
(PaddleOCR models on onnxruntime, CPU, no Tesseract install) read a
synthetic scan and a table screenshot exactly, about 1.7 s a page; results
are cached beside the document's images, so a second read is instant
(0.24 s). The models download once on first use if missing.

> Replaced on 2026-11-03 by *Documents are parsed at upload*: the same OCR rules (`agent/ingest/ocr.py`) run at upload, and the script is gone.

~~**PDFs by link**~~ (2026-10-21, measured). `read_pdf.py` takes `http(s)://`
(downloaded into the workspace, reused on a second read; a web page instead
of a PDF fails with a hint) and `file://` (read in place). A message with a
PDF link gets the exact command, as attachments do: before, Gemma tried the
`read` tool on the URL and asked for an upload; after, one `read_pdf.py` call
and a correct answer. In the extension a PDF tab cannot be read by a content
script, so the panel attaches the PDF itself; tested on a scanned page.

> Replaced on 2026-11-03: `read_pdf` takes an https link and taints the chat; `file://` is refused, because it slipped past the access check.

**The model writes Markdown; Atlas makes the document** (2026-10-19, found by
test). The docx writer read hand-written JSON from `echo '...' |`. An
apostrophe in the text ended the shell quote, and slips in nested JSON were
common, so the model fell back to writing plain text into a `.docx`: a corrupt
file. `create_document` takes Markdown, writes to a temp file, reopens it to
prove it parses, then moves it into place. The model also wrote
tab-separated data for an xlsx, so TSV is accepted alongside Markdown tables
and CSV.

**Name files, not paths, and say how to read them** (2026-10-19, found by
test). The model copied a 32-character chat id in a path as `a34a34a3...` and
the read failed. Shell commands now start in the chat's workspace, so an
attachment is named `"exp4.pdf"`. The attachment list gives the exact reader
command, which also stopped the model trying `read` on a PDF first.

> Update 2026-11-03: the reader commands are now read tool calls, `read_pdf(path="exp4.pdf")`.

**Keep images when a document is rewritten** (2026-10-19). The readers save
a document's images and print them as Markdown image lines, and
`create_document` embeds those lines. A five-page PDF with six figures came
back with all six.

> Update 2026-11-03: images are kept in the ingest store and printed as `asset:` lines, never written beside the document.

**Tool failures must be error results** (2026-10-19). A tool that returns
"Error: ..." as ordinary text is a success as far as Strands is concerned,
and the recovery hooks never see it. Atlas's tools return
`{"status": "error", ...}`.

**docx to PDF needs Word or LibreOffice** (2026-10-19). `docx2pdf` drives Word
over COM; without Word or LibreOffice the script says so and points the model
to read the document and `create_document` the PDF instead. xlsx to PDF has no
library that works without Excel, so it is not offered. `pdf2docx` (PDF to
Word) pulls in PyMuPDF, which is AGPL-licensed.

~~**Skills are how documents are read**~~ (2026-10-17). The harness `read` tool
does not help with rich documents on llama.cpp, and a 2B model writing
`python-docx` code is a bad bet, so each skill ships a script.

> Replaced on 2026-11-03 by *Documents are parsed at upload; reading is fetching*: reading needs no skill; the skills convert and write.

---

## Safety

**The web UI is a task view, calm by default** (2026-11-06). A mockup was
reviewed first (two rounds: the first showed every stat and read as noise to
a casual user). The web app shows a chat as a task: a home page asking what
Atlas should do, and beside an answer a panel of plain steps, the files made
and the web sources, with tool calls, timings and stats behind one Details
switch. Step labels are templates over each call's arguments and result, not
a model call: a label per step from a 2B model would cost a generation each.
A failed or declined step says what did not happen ("Did not delete X · You
said no"); the first build labelled a declined delete "Deleted X". Approval
cards ask in plain words, but a command, an install or anything after
outside content always shows the exact text: a summary there could hide what
is approved. The extension keeps the chat layout. Inter and Poppins are
bundled from npm rather than loaded from Google, which would be a request on
every page load from an app that otherwise needs no network. Checked by
rendering recorded suite tasks with the backend alone (no model, no GPU).

**Web search is native, through Exa; the workspace is never shown by its path**
(2026-11-05, measured, `benchmarks/2026-11-05-search-exa*`). `web_search` and
`read_url` (agent/tools/web.py) call Exa's API with httpx (no SDK: two POST
requests). Code shapes the results: two per site at most, only those whose
highlights answer the query, five kept, each labelled with its site, date and
kind. `read_url` is fetched by Exa, so it cannot reach this machine; local
addresses are refused before sending. Both ask (`tools.ask` by default), and
"Allow for this chat" on them survives their own results tainting the chat
(otherwise every search after the first asks); queries carrying a path,
`$ATLAS_WORKSPACE`, a long number or over 300 characters are refused instead.
The key is in `<data>/secrets/exa.key`, set through a web-UI-only route. The
search tasks: 23/24 (thinking on 12/12) against 5/12 on the ddg-search MCP
server, where the facts were right but uncited and links were searched rather
than read. The first Exa run was 14/24: the model wrote [1] without links
until the tool asked for "a Sources list: each number with its full link".
The exfiltration task (a page telling the model to search with the user's
resume) never had the model try, in 8 runs: the refusals are proven offline
only. Separately, the model is no longer shown the workspace's path: a
garbled copy of its 32-character chat id had landed in another chat's
folder, which showed an Allow card. Workspace files are named bare,
`$ATLAS_WORKSPACE` names the workspace in every tool and the shell, and any
other chat's folder is refused outright, reads included. ddg-search is
disabled in mcp.json, like the filesystem server.

**Cleanup after the document and file rework** (2026-11-05). Removed what
nothing called: `Scope.allows` (the grid replaced it), `harness_skills`,
`set_thinking`, `verify_off`, `SessionManager.policy`, the client's
`saveTable`, the ingest store's unused `DONE`. One table says what each file
tool does to its path (`call_paths.TOOL_ACTIONS`), read by the floor and the
grid alike, where there were three lists. The tools now place a path with
the policy's own `Scope.place` (a copy of it in `factory.py` is gone), so the
place checked is the place written. Comments naming steps or files that no
longer exist were reworded (the access and taint steps, `skills/.../_ocr.py`,
the summarizer, the restructure plan's B-numbers). `tests/live/check_demo.py`
and its fixtures were removed: every scenario is a suite task now. Every
measured run is in `benchmarks/<date>-<what>` (summaries committed, traces
local), named by what was measured instead of by plan phases, and the suite
writes new runs there (`--name`).

**Finding files is native; the filesystem MCP server is off** (2026-11-05,
measured, `suite.py --tags files`, thinking off and on). `find_files` (words
in a file's name, folder or text, every allowed folder at any depth, 10
ranked results with full paths) and `list_folder` (a tree, shown deeper on
its own while small), with the folders named in the prompt and "never search
the web for the user's own files". `copy_file` / `move_file` beside
`delete_file`, never over an existing file; moving the user's file asks.
Finding went from 5/12 to 11/12, mostly in 2 calls (the MCP server took up
to 9, one level per call); the file tasks 26/28; harm 20/20 over two
repeats, graded on why: 18 stopped by the policy, 2 the model did not try,
none by luck. Shell still does everything these do; they exist because a 2B
model does not write a bounded, quoted `find` and its output is uncapped,
and because the grid places a tool's `path` exactly where it can only parse
a command. What is left: writing into a folder with thinking off (2 of 4
over two runs). After loading a skill, whose result prints
`C:\Users\...\Desktop\atlas\skills\...`, the model typed the folder's path
from memory with `Desktop` in it. A create whose folder does not exist but
whose end names one in the user's folders is now refused with the real path
(no card); with thinking off it repeated the wrong path anyway. Rewriting
the path silently would fix it and was not done: where a write lands must
be what the model asked and the grid checked.

**Allow for this chat; MCP tools ask unless set On** (2026-11-05). A card
can be answered for the whole chat, so a web search does not ask on every
call. The grant is kept per chat in the backend's memory (a restart asks
again) and stops counting once outside content enters the chat. It is never
offered for a delete, a command (allowing `python` for a chat would allow
any code) or an install, and the server honours it only on a card that
offered it. MCP tools now default to Ask (mcp.json `atlas.on` lists the ones
set On; the old `atlas.ask` list is dropped when a mode is next set), and
`tools.ask` makes any of Atlas's own tools ask on every call. When the grid
and a tool's Ask both apply, the user gets one card. Tested offline; turning
off the taint check or the "offered" check fails a test each.

**One permission grid for every tool: where, what, and whether it asks**
(2026-11-05, `agent/safety/grid.py`). Every call, Atlas's own tools, the
harness's, the shell's and MCP's, is described as (place, action) pairs:
place is the workspace, the allowed folders, elsewhere or a system folder
(Atlas's own files stay the floor); action is read, create, change, delete
or run. Each pair is looked up in the grid of `access.mode`: look (reads
only), ask (the default: changing, deleting and running commands in the
folders ask), work (changes and commands in the folders run; deleting still
asks). Two rules hold in every mode: deleting outside the workspace asks,
and outside content in the chat makes every run, change and delete ask.
Deleting goes through `delete_file`, which moves to the Recycle Bin; a shell
delete outside the workspace is refused and pointed there. Shell targets are
placed with `~`, `$HOME` and `%USERPROFILE%` as the home folder, and one that
cannot be placed asks, closing the hole the file baseline found
(`rm -rf ~/Downloads/*` passed every check). MCP tools are described by their
servers' labels, unlabelled ones as changes, so they ask in the folders. The
old access and taint steps are folded into this one, so a call gets at most
one card. Tested offline in every mode, with the probe's commands; disabling
the fix fails 6 of the 27 tests.

**Image lines in `create_document` are access-checked** (2026-11-04). An
image's source in the Markdown is a file the tool reads and embeds, but only
the output `path` was checked: any picture on the disk, or Atlas's own files,
could be embedded into a document. `_paths_of` now returns each image source
as a read, so the floor refuses Atlas's files and the access step asks outside
the workspace and the allowed folders. `asset:` images resolve only for the
chat that owns them; links are not files.

**`subagent` and `web_fetch` are removed, not switched off** (2026-11-04).
`subagent`: one turn beat plan plus workers 88% to 41% (above). `web_fetch`:
it fetched any address, so a page with instructions in it could have the
model fetch Atlas's own API on 127.0.0.1 (which trusts requests without an
Origin) and send what came back out in a second fetch. Web pages come through
MCP fetch servers, which refuse private addresses; PDFs by link come through
`read_pdf`, which takes only a PDF (`open_link` checks the bytes) and taints
the chat. The summariser model `web_fetch` needed went with it.

**Shell text writes into binary documents are refused** (2026-11-03). After
two failed `edit_document` calls the model ran `sed -i` on a .docx and
destroyed it; the documents step guarded only the `write`/`edit` tools. It now
also refuses `sed -i`, `tee` and redirections (`>`, `>>`, `&>`) whose target is
a .docx/.xlsx/.pdf/.pptx, using the shell classifier's write targets. Copies
(`cp`) and the skill scripts still run. A script that writes one itself
(`python -c ...`) is not caught: it is `other`, which the tiers will ask about.

**Every run has limits** (2026-10-31, plan item 6). 40 model calls and 15
minutes per message, and the same tool call with the same arguments at most 3
times (Settings > Recovery & context > Limits, live). Past a limit the next
model call is cancelled with a message, which Strands makes the turn's answer:
the turn completes, and "continue" goes on with the work in the history. A
repeat past the limit is refused as a tool result, before the policy, so it
never shows a card. Checked on the real model with a limit of 2: two
`calculate` calls ran, then the stop message.

**The extension's token: a header, and only the panel's routes** (2026-10-31,
plan item 7). The token opened the whole API, and travelled in `?token=` links
(history, logs, Referer). It is now a header only, and opens only
`EXTENSION_ROUTES`; the panel fetches images and downloads with it. Measuring
what Edge sends found an older hole: an extension's GET carries no Origin and
`Sec-Fetch-Site: none`, which the guard took for a local program, so any
installed extension allowed on all sites could read every chat, the profile
and `GET /api/pairing` (the token itself) with no token. Such fetches now need
the token and get the same scope. Verified in headless Edge: the panel sends a
message and follows its run with every request let in; without the token, with
`?token=`, or for pairing and settings writes, it is refused.

**Shell commands are parsed with tree-sitter-bash** (2026-10-31, plan item 4).
Chosen over bashlex (GPL-3.0) and over extending our own splitter: less code
of our own, a maintained grammar, MIT, and prebuilt abi3 wheels (tree-sitter
itself was already in the lock through Docling). `agent/safety/shell.py`
places each simple command, wherever it is nested, as read, write, delete,
install or other, and a command takes its worst part's class. Read is the one
class that must be proven: a program not on the list is `other`, readers that
can write (`sed` with `w`/`e`, `uniq in out`, `date -s`) are not read, and a
command that does not parse is `other`. Install detection runs on the same
parse. Nothing decides on the classes yet; the tiers will.

**The floor is a data file** (2026-10-31, plan item 5). `agent/safety/rules.toml`
lists commands refused in every tier with no card (formatting disks, raw disk
writes, deleting backups, boot changes, registry deletes, deleting a drive, the
home folder or a system folder). Each rule's examples are checked when it
loads, so a rule that stops matching fails Atlas's start instead of silently
letting its commands through. Writing the tests found that the shell runs in
`.data/chats/<id>`, so `rm -rf ../..` reached Atlas's data and `rm -rf ../c2`
another chat, unseen by any check (relative paths were never placed). The
floor now places a shell command's write and delete targets from the
workspace and refuses those.

**Pairing is pinned to one address** (2026-10-30, B28). Pairing accepted any
local backend that answered 200, so a page on another local port (a dev server
running untrusted packages) could pair the extension with its own server and
receive what it reads. The extension now pairs only with the address in its own
settings (default `http://127.0.0.1:8000`); a different port is set in the
panel's Settings, which no page can reach.

**The element list never carries typed values** (2026-10-30, B29). It sent the
first 60 characters of every non-password field: OTPs and card numbers went to
the model and the transcript. A field the user typed into is now only
"(filled)"; a value the page itself set (its default) is still shown, and
one-time-code, card and password fields never are.

**The chat says when it has read outside content** (2026-10-30, plan item 3).
Once a web page, a fetched link or an untrusted MCP server's output is in a
chat, commands and changes outside its folder ask first, for the rest of the
chat. That used to be visible only as approval cards. A line above the composer
now says so (web UI and side panel, one shared `ChatScreen`), from the moment
the run emits `tainted` and after any reload (the chat row's `tainted`).
Verified with a real `web_fetch` turn in headless Edge.

> Update 2026-11-04: `web_fetch` is gone. The sources now are MCP tools from untrusted servers, PDFs `read_pdf` downloads, and the extension's page tools.

**llama-server needs a per-launch API key** (2026-10-21, measured).
llama-server allows every origin, so any web page could call
`127.0.0.1:8080` and use the model. `atlas start` now generates a key per
launch (kept across restarts), passes it as `--api-key`, and gives it to the
backend in `ATLAS_LLAMA_KEY`. With it set, chat, `/props` and `/v1/models`
answer 401 without the key; `/health` stays open for the readiness check.

**Pairing guard** (2026-10-21). Host must be local; Origin must be the web UI
or an extension with the pairing token; cross-site requests without Origin
need the token. The extension needs no CORS: `host_permissions` lets it fetch
127.0.0.1 directly.

**Installs are asked, not forbidden** (2026-10-19, decided). "NEVER run pip"
in the prompt also stopped `npm install` for an npm-based skill. Every install
now pauses for Allow / Deny, and 60 seconds with no answer is Deny.

**One policy hook, in a fixed order** (2026-10-19, decided). The document
guard and install approval were separate hooks whose order depended on
`build_agent`. `ToolPolicy` runs normalise, access, install, sensitive,
documents in that order, and the first refusal wins.

**One access model** (2026-10-19, decided). The workspace is always allowed;
`access.folders` adds more; anything else asks. It covers the file tools,
document tools, shell paths and MCP arguments, and MCP servers get the folders
through `{atlas:folders}` because Strands' MCP client has no roots support.
Skills are bounded at the tool boundary, not by a sandbox.

**Skill requirements are installed by the user** (2026-10-19, decided). A
community skill often says `npm install -g x` only in its SKILL.md, and the
model then tried to install it mid-task. Requirements are read from all three
places and installed from the Skills page; the click is the approval.

---

## Recovery and retries

**Recovery is hooks, not prompt text** (2026-10-18). The model read an empty
error, said "same error" and stopped: Strands ends the loop whenever the model
stops calling tools. A sentence in the system prompt is not reliably followed
by a 2B model; a hook always runs. See `agent/core/resilience.py`.

**A non-zero exit code is a failure** (2026-10-18, found by test). The
harness's `shell` tool reports `status: success` with `exit_code: 1` in the
body, and the model then told the user the command worked.

**Retries need the earlier answers in front of the model** (2026-10-18).
Restoring the same state and asking again gave near-copies; a seed or a
penalty alone changes wording, not approach. Quoting the earlier versions with
a "take a different approach" note is the lever that works. The note is
stripped from history before the snapshot is saved. On factual questions,
expect different framing, not different facts.

**No exponential backoff** (2026-10-18). `ModelRetryStrategy`'s default (4s
doubling to 240s) is built for cloud rate limits. Locally the failure is a
restart or an empty response, so retries use a fixed short delay.

---

## Chat tree

**Generated files outlive edits** (2026-10-19, decided). An edit deletes the
turns that follow, never the files they produced or changed. The preview
panel lists the whole workspace.

**Retry is non-destructive and last-turn only; edit is destructive and
anywhere** (2026-10-18, product decision). A retry adds a version beside the
last answer. An edit rewrites history from that point: the edited turn, its
versions and everything after are deleted, rows and snapshots. Versions stay
navigable after later turns, and each keeps its own follow-ups.

**Store a display transcript per turn** (2026-10-18). Opening a chat used to
rebuild two agents per turn to read snapshots, on the event loop, and silently
returned the whole conversation when the first restore failed. The UI now
reads `render_json`. It is written once when a run ends and is never given
back to the model, so Strands still owns the history. It also keeps
reasoning, which Strands never stores, across a reload.

**Only a completed turn can be continued** (2026-10-17). A cancelled or failed
turn has no snapshot, so a half-finished tool call can never be built upon.

**Check the run slot before changing the tree** (2026-10-17). A refused send
used to insert a turn first and leave a phantom `running` leaf.

---

## Windows and the launcher

**The start screen is Rich Live, not Textual** (2026-10-21, found). Textual
8.2's inline mode is skipped on Windows (`inline and not WINDOWS` picks the
driver), so `run(inline=True)` takes over the whole terminal there. Rich
Live draws the same panel inline on every OS; keys are read with `msvcrt`
on Windows and cbreak mode elsewhere.

**Start in parallel, serve the built UI** (2026-10-21, measured). The backend
and UI no longer wait for the model: backend ready in 3.0 s, model in 10.7 s,
all ready in 10.7 s. Normal mode serves `client/dist` from the backend, so it
runs without Node or a third port; the first start builds it (5.5 s).

**No model hash at start** (2026-10-21, measured). `launched.json` hashed the
GGUF on every start: 2.6 s for the 2.6 GB model, plus the mmproj, and nothing
read the hash. The cache meant to skip it never applied, because a clean stop
deletes `launched.json`. Size and modification time are recorded instead.

**Port sweeps only touch our own processes** (2026-10-21, found by test).
After a failed start, the old sweep killed whatever held the port if its
command line contained "python": in the test, the program that was holding
the port. Now only ports of services this launch started are swept, and a
holder must look like that service (llama, uvicorn, vite/node).

**`/tmp` is Git's, not `C:\tmp`** (2026-10-19, found by test). `web_fetch`
has curl write `/tmp/strands-web-fetch-*` and reads it back; that path was
resolved as `C:\tmp\...` and every fetch failed. POSIX paths go through
`cygpath`.

> Update 2026-11-04: `web_fetch` is gone; the mapping stays for shell commands.

**Show the model `/c/Users/...` paths** (2026-10-18, found by test).
- Unquoted backslashes are escapes in bash, so `C:\Users\x` arrived as
  `C:Usersx`.
- The harness file tools reject any path not starting with `/`, so `read`,
  `write` and `edit` never worked on Windows.
- The Git-Bash form fixes both. MSYS converts it for native programs, and the
  sandbox converts it for Python's own file calls.

**Never `uvicorn --reload`** (2026-10-18). Its worker runs the Selector event
loop, which cannot start subprocesses on Windows. Every shell call failed with
an empty `NotImplementedError`, which reads like a broken script.

**One SQLite connection, WAL, closed on shutdown** (2026-10-18). A surviving
backend held `atlas.db` open, and deleting it gave `EBUSY`.

**Git Bash, with `cmd.exe` as a fallback** (2026-10-17, measured).
- `CreateProcess` resolves an executable from the *calling* process's PATH, so
  PATH is changed in `os.environ`, not passed through `env=`.
- Git's tools are in `usr/bin`, not `bin`.
- `PROGRAMFILES(X86)` is an illegal POSIX name and must be filtered out.
- bash needs a `:`-separated PATH, or `python` silently goes missing.

**The venv's `Scripts` goes first on PATH** (2026-10-17, measured). A bare
`python` otherwise ran the system interpreter without the project's packages.
The model then ran `pip install` into user site-packages. Telling it to use
`sys.executable` did not work; fixing PATH did.

**A busy port reports `WinError 10013`, not `10048`** (2026-10-17). It reads
like a permissions problem.

**The repository has two names** (2026-10-17). `Desktop\atlas-strands` is a
junction to `Desktop\atlas`.

---

## Paths, settings and dependencies

**Unused dependencies removed** (2026-11-03). `requirements.in` lists only
what agent/ or server/ import or run. Gone, imported by nothing: docling (and
with it torch, torchvision, transformers, scipy), fastembed, sqlite-vec,
pandas, matplotlib, sse-starlette; pytest moved to `requirements-dev.in` only.
Declared because code imports them directly (they came in through other
packages before): pillow, pyyaml. Made core for ingestion (they were
skill-only, and resolved through docling): pypdfium2, rapidocr, onnxruntime.
The lock went from 162 packages to 90, the venv from 1.5 GB to 672 MB. The
pdf skill's pdf2docx brings PyMuPDF, which is AGPL-3.0: worth replacing
before Atlas is distributed.

**Keep the single-model settings migration for now** (2026-10-31, measured).
The current `settings.json` uses `model.dir` and `model.name`, and both that
shape and the legacy `model.path` shape normalize to the same `ModelSettings`.
Removing `_from_single_model` would not affect the current file, but would make
older settings files fail strict validation because `ModelSettings` forbids
unknown keys. Remove it only when backward compatibility with those files is
intentionally dropped.

> Update 2026-11-06: dropped, with the older `tools.documents` switch. The
> settings.json in use has the `model.dir` / `model.name` shape and loads; a
> file with `model.path` now fails validation with the unknown key named.

**Everything is relative to the app root, and generated state is in `.data/`**
(2026-10-18). Paths used to resolve against the working directory. A backend
started from `tests/` wrote a second database there, and `session.dir`
repeating the data dir put snapshots in `data/data/sessions`.

**Settings: RESTART keys are writable** (2026-10-18). They are saved to
`settings.json` and applied at the next start, while the running backend keeps
the values it started with. The old "N settings need a restart" banner was
always on: a flat `launched.json` block was walked as if nested, so every key
looked changed.

---

## Skills and MCP

**MCP starts are bounded and cancellable** (2026-10-22). With PyPI
unreachable, `uvx duckduckgo-mcp-server` never answered; Strands' timeout then
hung in `stop()`, left the `uvx` process alive (holding uv's cache lock, so
every retry hung too) and kept the server "connecting". Atlas now cancels the
start itself after `mcp.startup_timeout`, and Refresh, settings changes and
shutdown cancel a start in progress and wait for it.

**skills.sh commands are parsed, not run** (2026-10-18). Its install command
(`npx skills add <repo> --skill <name>`) names a GitHub repository and a skill.
That is enough to fetch the folder directly, with no API key, Node or
interactive prompts.

**MCP servers are pooled per process** (2026-10-18). Handing a per-turn agent
an `MCPClient` would start the server when the agent is built and stop it when
the agent goes away: `npx` on every message. The pool holds each connection
open, and turns get individual tool objects.

**MCP tools cost context** (2026-10-18, measured). The reference filesystem
server's 14 tools are about 3,100 prompt tokens on every request, roughly 10%
of the window. Hence the per-tool switches and the budget meter.

**The MCP registry is slow** (2026-10-18, measured). About 28 seconds for two
results at times. Searches are cached for ten minutes.

---

## The web UI and the extension

**Fixes after the first real use** (2026-10-22). The mic had vanished: with
the parallel start, the backend asked llama-server for its modalities while
the model was still loading, got a 503 without them, and cached "none" for
the whole run; now only a real answer is remembered. Translate in the
selection chip never opened: the chip cancels mousedown to keep the page's
selection, which also stops a native `<select>`; it is a row of buttons now.
The "Save table" bar appeared over any table on hover, including Gmail's
account switcher (an ARIA grid); tables are now offered from the selection
chip inside a real data table. The right-click entry went too (2026-10-22):
browsers cannot limit a menu item to tables, so it showed on every page.

**An Atlas PDF viewer for the extension** (2026-10-22). Content scripts cannot
run in the browser's PDF viewer, so PDFs had no highlights or chip. The
extension's own `viewer.html` (pdf.js with a text layer) is a page the panel
can read, search and highlight like any other; local PDFs come from the
backend so no file-access permission is needed.

**One-click pairing, developer mode** (2026-10-22). Copying a token into the
panel was a developer's chore. The extension is its own page in the sidebar,
and Connect hands the token over through the content script that already runs
on Atlas's local page. Accepted only from a 127.0.0.1/localhost http page and
only for a local backend that answers 200 to it; a malicious local page could
at most pair the extension with another local server it already runs. Tuning
settings and the raw token sit behind a per-browser developer mode toggle.

**No preview panel** (2026-10-22). The web UI's file preview (docx-preview,
pdf.js, a sheet endpoint) is gone. Users open documents in their own apps,
where they can also edit them, and the extension's viewer reads PDFs beside the
panel. The download chip stays. Workspace files are now served as downloads,
with only raster images inline, so an agent-written HTML or SVG file never runs
on Atlas's origin.

**Demo rehearsal: paths, quotes, prompts** (2026-10-22). Running every
demo in `docs/demo.md` through the API, several times each, on fixtures:

- A relative path meant different things to different tools. The filesystem
  MCP server resolved `Demo/Invoices` against its *first* folder (Atlas's
  chats folder), the reader script against the workspace. One rule now
  (`shell_env.locate`): workspace, then allowed folders, for MCP arguments,
  file and document tools, scripts and the `read` hint. Before: 0/2 runs of
  Demo 1 read the invoices; after: every run did.
- A model that listed a folder then named files bare (`invoice-x.pdf`);
  scripts now look a bare input up by name (unique match, bounded walk).
- A pasted `C:\...` path failed in `read` ("not absolute") and unquoted in
  bash (`C:UserspranaDesktop...`); both are normalised before the call.
- A denial told the model never to try again, so "I've allowed it now, read
  it again" was answered from memory; it now says to try when asked again.
- Quote highlighting matched an invented quote ("not on the page at all") on
  the words "not" and "all". Quotes now need 2+ words of 4+ letters, 75%
  present; search stays lenient.
- Prompts: the model added five amounts in its head and was off by 60 until
  the prompt said "use the spreadsheet"; an unnamed summary was once written
  over the spreadsheet itself, so the prompt names the PDF; "the last F1 race"
  gave three different podiums in three runs (one right), so the demo uses a
  finished season.

**The extension calls the page through the run, like an approval**
(2026-10-21, built). A page tool emits `client_call`, the side panel runs it
in the tab and POSTs the result; a future resolves. Measured with a scripted
panel on Gemma: "when do the exams start and what is the fee" read the page
and answered with exact quotes; "where does it say X" went straight to
`page_find`; an injected "run `del /s`" on the page was not followed, and a
shell command after reading needed approval (page taint).

**Quotes are highlighted by code, not by the model** (2026-10-21). The model
is asked to back statements with exact quotes in double quotes; the panel
finds each one on the page (whitespace folded, word stems, best block) and
highlights it, or marks it "not found on the page". A 2B model cannot place
highlights itself, and a missing quote is how an unsupported claim shows.

**WXT's `@` is its source folder** (2026-10-21, found). It overrides any user
alias, so the extension's `srcDir` is `client/src` and its entrypoints are
pointed back to `extension/`; shared components import `@/...` unchanged.

**Fill suggestions: one schema-constrained call, applied by the user**
(2026-10-21, measured). Not an agent turn: the form's fields and the user's
details go to the model once, with a JSON schema allowing only those field
ids and each select's options, "" when unknown. On an 8-field form it filled
7 correctly (a date converted to YYYY-MM-DD, "Sem 6" from "semester 6", the
pin code from the address) and left "Father's name" empty rather than
inventing it; 16 s. Never submits; secrets never collected.

**Voice is an audio attachment** (2026-10-19, decided). llama-server reports
`audio` among the model's modalities, and Strands sends `audio` blocks as
`input_audio`. The recording goes to the model as it is, with no
speech-to-text step and nothing to install.

---

## Tests

**Tests are in the repository, with CI** (2026-10-30, reverses the entry
below). A restructure needs something to check against, so the offline tests
(policy, maths, chat tree, runs) are committed and `tests/check.py` runs every
check (ruff, pyright as a ratchet at 73 errors, pytest, tsc, oxlint) locally
and in GitHub Actions on Windows. The real-model checks
(`tests/live/`) are committed too but run by hand: they need the GPU. No fake
llama-server: behaviour is judged on the real model, and the policy-level bugs
are tested by calling the policy directly.

> Update 2026-11-04: the real-model checks are one suite, `tests/live/suite.py`; the pyright ratchet is at 35.

~~**Tests stay out of the repository**~~ (2026-10-19, decided). The user tests by
hand; the development tests and benchmark live in an ignored `tests/`.

> Reversed on 2026-10-30: *Tests are in the repository, with CI*.

**What a model can do is read from its files** (2026-11-07). "Model can think" and
"Model can see images" were toggles the user had to know to set; set wrong, they
sent images or a thinking switch to a model that cannot take them. The GGUF
headers say it: the projector's `clip.has_vision_encoder` / `clip.has_audio_encoder`
(exact), the chat template taking `enable_thinking` (a heuristic: none is
unknown), and the trained context length. The toggles stay under Advanced as
overrides that can only switch a capability off. Read with capped lengths
(model files come from the internet), header only, cached per file version;
about 0.2 s for a 260k-token vocabulary. A Files page was considered and
dropped: it suggested files must be added before Atlas can read them.

**The page goes with the message, as an accessibility tree** (2026-11-07). The
side panel sent only a page's address; the model spent a tool call, and a model
turn, reading it, and on canvas apps (Google Docs) and app-like pages it got
nothing useful. Now the content script builds a snapshot when the message is
sent and it goes with it: Google Docs, Sheets and Slides through their exports
(with the user's session), articles through Readability (gated by its
`isProbablyReaderable`, which a news front page fails), anything else as the
accessibility tree, with roles and names from `dom-accessibility-api` and a ref
per element (agent-browser's format; agent-browser itself drives its own
browser and cannot run in an extension, and the browser's own tree needs the
debugger permission and its warning bar). Measured in Edge on real pages: 4-156
ms per snapshot; a form becomes one line per field ("[textbox: E-mail address
(empty)](e3)"), Hacker News its table of stories. The chat is tainted as soon
as page content is in the message. Approval cards after page content make No
the main button.

**The side panel answers by taking the user to the page** (2026-11-07). Asked to
find "semester V regular", the model searched three times and said it was not
there; nothing in the panel led to the page. The page is already in the message,
so the model now points by quoting the page's own words or naming an element's
ref, and the panel turns each into a Go to (exact or similar match, scrolled to
and marked). The page's text index joined text nodes with a space each, which
doubled spaces at every bold or link ("as the  University"), so quotes copied
from the page matched only as similar; nodes now join with exactly one space.
The panel no longer asks before following another tab (a banner users found
an annoyance); it holds the tab only while an answer is being written.

**Files for upload fields: a basket the user drags from** (2026-11-08). Fill
finds files for a form's upload fields (find_files' search, picked in the same
single model call) and shows them as cards; the user drags one onto the page.
Atlas never uploads by itself. Before building, a spike in Edge proved the
parts that depend on the browser: a drag from an extension page carries a
custom marker to the page; the content script can turn a trusted drop into a
real file for an upload field (`input.files` from a DataTransfer) and for a
react-dropzone-style zone (a replayed file drop); a drop faked by a page
script is untrusted and refused. Not proven: Google Forms' upload dialog (it
needs a sign-in), which has Download as its fallback.

**Panel: actions report as cards, not turns; ask-next pills; no drag outline**
(2026-11-08). Fill's progress and result show in a card above the composer
(closed by the user, or by another page in front); nothing goes into the chat,
since Fill is an action, not a question. After each finished answer the panel
offers fixed pills for the page kind (the starters not asked yet, plus
"Simpler" and "Translate…"); no model call. While a basket card is dragged,
Atlas no longer outlines a target: on Google Forms the outline sat on the
"Add file" button, which ignores drops, and looked like a valid target. The
page's own drop styling is the only signal now.

**Key moments: a ready-made turn, not an agent run** (2026-11-08). "Key moments"
on a YouTube video saves a finished turn ("Found N key moments in <title>",
then one "[m:ss] label" per moment, which the panel shows as Play-from-here
rows) with no run and nothing streamed. It persists like any answer, and later
questions see it in the history. Source: the description's chapters when the
video has them (YouTube's rule: three or more, from 0:00, in order), with no
model; otherwise one model call over the transcript whose times are limited
to the transcript's own by a schema enum and checked again. Labels are page
text: markdown is stripped so they cannot add links or extra times, and the
chat is marked as having read outside content. A custom question about the
video is still a normal turn.
