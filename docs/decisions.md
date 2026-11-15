# Decisions

Why Atlas is built the way it is. Atlas runs a 2B model (Gemma E2B) on one
4 GB GPU, so most of what a cloud agent does by default was measured here and
rejected, and most of what Atlas does instead is code where an agent would ask
the model. Each entry says what was decided and the evidence. Superseded
entries are deleted, not struck through: git has the history, and
[benchmarks/BENCHMARKS.md](../benchmarks/BENCHMARKS.md) has the measurements.
How the system works today is in [ARCHITECTURE.md](../ARCHITECTURE.md).

When a decision changes, rewrite its entry. Add an entry only for something a
future change could plausibly undo by accident.

---

## A small local model: code does what the model cannot

**One agent, one turn. No plan tool, no workers.** Measured on multi-part
tasks with planted facts, 36 runs each: one turn 88% complete, plan plus
workers 41% (the parent delegated one file twice, never merged, said it was
done); one turn 97%, the plan tool 63% (the plan competed with the work). A 2B
model cannot hold a plan, track workers and merge results. `subagent`,
`todo_write` and their settings are removed, not switched off (2026-11-04).

**Code loops; the model answers one question per unit.** For work with a known
shape, code iterates and asks the model one schema-constrained question per
file, section or change (`ModelCall`), checks every value against its source,
and assembles the result: `extract_table`, `write_summary`,
`compare_documents`, `fill_template`, Fill, Key moments. The evaluation that
led here (2026-11-12): the agent made 6 correct files in 19 runs on five
document tasks, the right ones in 84 to 112 s; a prototype pipeline on the same
inputs got 48/48 invoice fields in 11 s and 8/8 section figures. A value that
fails its check is left out and named, never kept. 86% of model time is
generation, so retyped data is the cost, not prompt reading.

**The model never retypes data.** It copied reader marks into documents, typed
totals (6,776.70 for 7,260.44) and dropped rows. `create_document` takes
references that code fills from the file (`{{report.docx#t1}}`,
`{{sales.xlsx!North!A1:C41}}`, `{{orders.csv sql: ...}}`); every CSV, sheet and
Word table read ends with how to reference it; reader marks are stripped from
whatever is written. Typed figures that appear in no source send the turn back
once (`provenance.py`).

**Code decides when a turn is done.** Strands ends a turn when the model stops
calling tools; in 5 of 19 runs that was before any file existed ("Now I will
create the spreadsheet."). `DoneCheck` sends the turn back once if a document
it made does not open, the asked-for file does not exist, the last line only
announces a step, or a summary read part of a PDF.

**Recovery is hooks, not prompt text.** A 2B model does not reliably follow
"retry on failure"; a hook always runs. Tool failures must be error results
(text saying "Error" is a success to Strands). A shell command with a non-zero
exit is a failure (the harness reports success). A retry quotes the earlier
answers and asks for a different approach (a new seed only changes wording).
Retries of a model call use a short fixed delay: locally the failure is a
restart, not a rate limit.

**Typed tools, not a shell.** Given a shell, the model wrote unbounded `find`s,
pasted rows into `python -c`, saved CSV text as `.xlsx`, and every safety hole
found in review was a shell form the classifier did not know. Finding a file
went from 5/12 to 11/12 with `find_files`/`list_folder`. Skill scripts run
through `run_skill` (an argv list, no shell). The shell is off by default; when
on, every command asks with its full text. Arithmetic goes through `calculate`
and `dates` (the model added five amounts in its head and was off by 60).

**Thinking is the user's choice.** A per-turn guess by code was built and
removed (2026-11-14): a 2B model is worse with thinking off, and the guess saved
seconds at that cost. The composer toggle is the only control.

**Memory is off, with all four switches.** The harness's memory is a flat
folder keyed by nothing, injected every turn: a fact from one branch of a chat
leaked into another. `memory`, `context_manager`, `background_tasks` and
`builtin_plugins` must all be off (`background_tasks` alone still put a tool in
every request). Test isolation on bytes on disk, never on answers.

**Old tool results become stubs, nothing is summarised.** Near the window,
earlier turns' tool results are replaced by a one-line stub, oldest first; the
answers stay. Strands' summarizing manager had the model rewrite history.
History changes only when the trigger is crossed, so the cached prefix holds.

**8192 output tokens per call.** With 2048, a rewritten document ran out mid
tool call and the truncated arguments ran `create_document` with `{}`.

---

## llama.cpp on one small GPU

**One model at a time, switched by restart.** The router mode costs nothing per
token but every switch costs a full load (7.6 to 11 s) and an empty prompt
cache (4 s), so per-turn model switching is out. Settings > Model plus Restart.

**One slot.** A second slot was measured twice: two jobs finish 20% sooner, but
Atlas rarely runs two at once, and llama.cpp keeps the chat's prompt cached
across a pipeline's calls even with one slot (6,500+ tokens reused). The second
slot saved 0.2 to 0.35 s a turn for 0.21 GB of 4 GB VRAM.

**The prompt prefix never changes within a day.** llama.cpp reuses the longest
shared prefix, so the system prompt carries only the date (the time goes at the
end of each user message), tools are registered in a fixed order, and the
workspace is never named by its path. Only the first chat after a launch reads
the ~4.8k-token prefix (~2 s), so it is neither saved to disk nor trimmed
(its largest parts, the `calculate` and `dates` examples, are what keep the
arithmetic right).

**The stock adapter needed five fixes.** Stream the response (`client.post`
buffered it whole). Send `enable_thinking` every time (it was dropped; the
server defaults to on). Pass the current turn's reasoning back as
`reasoning_content` (without it the model lost its plan after every tool call:
6 calls and 38 s became 2 and 14 s; Gemma's template drops older turns'
itself). Send images as separate blocks (a combined image+text block drops the
text). Turn `document` blocks into text (llama-server answers them with 400).

**What a model can do is read from its files.** Vision, audio, thinking and
context length come from the GGUF headers, read with capped lengths; the
settings toggles can only switch a capability off.

**llama-server gets a key per launch.** It allows every origin, so any web page
could use the model. `/health` stays open for the readiness check.

**No `--tools all`.** That is llama.cpp's own tool set: a second shell beside
Atlas's.

---

## Strands and the harness

**Build on the harness, one agent per turn.** `create_harness` gives tools,
skills, sessions and MCP; Atlas configures it. A new agent every turn is the
only way a changed setting applies to the next message.

**Snapshots are immutable and always named.** `save_snapshot(is_latest=False)`
under a time-ordered id, so every branch stays restorable and switching
versions is a restore. Never `snapshot_latest`: Strands restores it on every
start, so a first message would begin with the previous conversation.

**The prompt is set again after every restore.** The snapshot's stored prompt
wins over the one passed in, so an edited prompt would never reach a chat with
history. It is recomposed with the harness's own builder.

**Events come from `stream_async`.** Text, reasoning, tool arguments and tool
results; no custom UI hooks. Reasoning arrives twice (raw and normalised): only
the raw one is used. Usage is on the raw `metadata` event. The printing callback
handler is off (a cp1252 console failed the run on an emoji).

**A trace per run, on disk as it happens.** Every event, the exact body of every
model request, every response and every policy decision, flushed line by line
to `<data>/traces/`. A crashed turn is shown from its trace; `atlas trace` and
`atlas replay` read it. Kept 14 days, deleted with its chat.

**What Atlas assumes about Strands is tested** (`test_harness_contract.py`): the
memory switches, the hook fields Atlas sets, reasoning stored once, the cancel
signal, no latest snapshot, the prompt after a restore.

---

## Documents

**Parsed at upload; reading is fetching.** One worker parses each file into
blocks in one SQLite database with FTS5 (a PDF's text layer first, scanned
pages as OCR finishes, pages a read waits for first). Shared by content hash,
owned per chat. Questions on a 12-page scan went from 25.7 s to 3.3 s.

**Typed readers, capped and searchable.** `read_pdf`/`read_docx`/`read_xlsx`/
`read_text` stay near 1,500 tokens, say what they left out and the exact next
call, and search by words. The harness `read` returned a 3,000-line log whole
and overflowed the window.

**The model writes Markdown; code makes the file.** Hand-written JSON broke on
the first apostrophe and the model then wrote text into a `.docx`. Every
document is written to a temp file, reopened to prove it parses, then moved.

**A file is never replaced.** An existing name gets `-2`: after failed edits the
model regenerated a workbook over the original with one month's figures in
another's place. Skill scripts' outputs follow the same rule. The one exception:
a file the same turn created may be made again.

**Edits are by address, on a version the chat read.** `edit_docx` takes a block
id (`b12`, `t1.r3.c3`), `set_cell` a cell (`Mar!B2`).

**Writing tools come with their skill.** A chat that only reads never carries
them; a message naming a document type starts with them. The tool order is
fixed (it is part of the cached prefix).

**SQL over a workbook or CSV is sealed.** DuckDB's own readers could open any
file on the disk; the connection is closed to files once the data is loaded.

**The allowed folders are indexed, text only.** So `find_files` finds a
document by what it says. Scanned pages wait for a chat to read the file, so
indexing never OCRs everything.

---

## Safety

**Guardrails are code, at four places.** Input: every tool result with outside
text is fenced (`<untrusted source=...>`), and text addressed to the assistant
taints the chat and shows a notice. Action: `ToolPolicy`. Egress: one gate for
everything that leaves the machine (shape, a budget once tainted, no 12-word run
copied from the chat's documents). Output: figures need a source. No model
judges anything, so no rail adds latency. Measured: 0 leaks in 12 injection and
exfiltration runs.

**One permission grid for every tool.** Each call is (place, action) pairs
looked up in the mode's grid (look, ask, work). Atlas's own files and other
chats are a floor no mode reaches. An attached file asks before change or
delete. After outside content enters a chat, every run, change and delete asks,
for the rest of the chat. A delete goes to the Recycle Bin through
`delete_file`. Before the grid, `rm -rf ~/Downloads/*` passed every check.

**The floor is a data file.** `rules.toml` lists commands refused in every mode;
each rule's examples are checked at load, so a rule that stops matching fails
the start.

**Grants are narrow.** "Allow for this chat" is never offered for a delete, a
command or an install, and stops counting after outside content. Allowing a
command covers that exact text, never its program.

**Installs are asked, not forbidden.** "Never run pip" also stopped legitimate
`npm install`s. Skill requirements are installed from the Skills page; the
click is the approval.

**Web access is through Exa, never fetched from this machine.** `web_fetch`
could have a page make the model call Atlas's own API on 127.0.0.1; it is
removed. Queries and addresses that carry a path or a long number are refused.

**The extension's token opens only the panel's routes, in a header.** Measuring
Edge found any installed extension could read every chat without it. Pairing is
pinned to one address; typed field values never leave the page; images in
answers are never loaded (an image URL can carry chat text out).

---

## Chats

**Retry adds a version; edit rewrites from that point.** Retry is last-turn
only and destroys nothing. Edit deletes the turn, its versions and what follows
(rows and snapshots), but never the files they made.

**Only a completed turn can be continued.** A cancelled or failed turn has no
snapshot, so a half-finished tool call is never built on.

**The UI reads a stored display transcript.** Never given back to the model, so
Strands owns the history; it also keeps reasoning, which Strands does not.

---

## The browser extension

**The page goes with the message.** Google files through their exports,
articles through Readability, anything else as an accessibility tree with a ref
per element (4 to 156 ms). The chat is tainted the moment page content is in it.

**Answers point at the page; code highlights.** The model quotes the page's
words or names a ref; the panel finds and marks them. A quote not on the page is
marked as such: that is how an unsupported claim shows.

**Fill is one schema-constrained call, applied by the user.** Only visible
fields are collected; nothing is filled until Apply; nothing is ever submitted.
Files for upload fields are offered as cards the user drags; Atlas never
uploads.

**Key moments is a ready-made turn.** From the description's chapters when the
video has them, else one call whose times are limited to the transcript's.

---

## Tests

**Tests live in the repository and run in CI on Windows.** `tests/check.py` runs
ruff, pyright (a ratchet), pytest and the TypeScript checks. Real-model checks
(`tests/live/suite.py`) run by hand on the GPU, graded by script, never by a
model. No fake llama-server: behaviour is judged on the real model.
