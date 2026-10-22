# Decisions and findings

Why Atlas is built the way it is. Each entry is something that was observed or
decided, with the evidence, so nobody has to rediscover it. Newest first within
each topic. Add to this file in place; when an entry stops being true, strike
it through and say what replaced it, rather than deleting it.

---

## Strands and the harness

**Build on the harness, not the plain SDK** (2026-10-16). `create_harness`
returns a normal Strands `Agent` with tools, skills, sessions and MCP built in.
Atlas only configures it. Everything Atlas adds is listed in the README.

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

**Snapshots are immutable and restorable from any branch** (2026-10-17,
measured). `save_snapshot(is_latest=False)` writes a new file under a
time-ordered id. A later restore-and-rerun does not touch it, and snapshots
from abandoned branches stay restorable. So switching versions is a restore,
never a recomputation.

**Usage arrives on the raw `metadata` event** (2026-10-18). Not on
`messageStop`, which the first event parser read.

**Reasoning is reported twice** (2026-10-18, measured). Once as a raw
`contentBlockDelta.reasoningContent` event and once as a normalised
`{"reasoningText": ..., "delta": ...}` event. Translating both doubled every
word on screen. Only the raw one is used.

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

---

## llama.cpp and the model

**Stream the response** (2026-10-18). The stock adapter used
`client.post(...)`, which makes httpx read the whole body before returning, so
each model call arrived in one burst. Most visible with thinking on, because
the wait is longer. The adapter now uses `client.stream(...)`.

**Strip reasoning from history** (2026-10-18, found by test). With thinking
on, Strands keeps a `reasoningContent` block in the assistant message, and
`LlamaCppModel._format_messages` raises `content_type=<reasoningContent> |
unsupported type` on it. Every model call after a tool call failed. Reasoning
is now dropped before sending; it was never meant to be replayed.

**Replace `document` blocks** (2026-10-18, found by test). The harness `read`
tool returns a pdf/docx/xlsx as a `document` block for cloud models that can
view one. llama-server rejects it with a 400 and the run fails. It becomes a
text note pointing at the skill.

**Thinking needs an explicit flag** (2026-10-17, measured). The stock adapter
copies a whitelist of request keys and drops `chat_template_kwargs`. The server
defaults to thinking on, so `enable_thinking` is always sent. On/off only; no
effort or budget control was verifiable.

**Images are separate blocks** (2026-10-17, measured).
- `LlamaCppModel` converts `image` blocks to `image_url` data URIs.
- `source.bytes` is required.
- A combined `{"image": ..., "text": ...}` block silently drops the text, even
  though the adapter's own docstring shows that shape.

**Context meter from `timings`** (2026-10-18). With `timings_per_token`,
llama-server sends `cache_n`, `prompt_n`, `predicted_n` and speeds on each
chunk. Context in use = `cache_n + prompt_n + predicted_n`.

**Not `--tools all`** (2026-10-17). That is llama.cpp's own tool set. Passing it
would show the model a second shell and file tool beside the Strands ones.

---

## Documents and installs

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

**8192 output tokens per model call** (2026-10-19, found by test). With 2048,
reasoning plus a rewritten document ran out mid tool call. Strands could not
parse the truncated arguments, ran `create_document` with `{}`, and the model
had to write the whole document again.

**Keep images when a document is rewritten** (2026-10-19). The readers save
a document's images and print them as Markdown image lines, and
`create_document` embeds those lines. A five-page PDF with six figures came
back with all six.

**Tool failures must be error results** (2026-10-19). A tool that returns
"Error: ..." as ordinary text is a success as far as Strands is concerned,
and the recovery hooks never see it. Atlas's tools return
`{"status": "error", ...}`.

**Installs are asked, not forbidden** (2026-10-19, decided). "NEVER run pip"
in the prompt also stopped `npm install` for an npm-based skill. Every install
now pauses for Allow / Deny, and 60 seconds with no answer is Deny.

**Generated files outlive edits** (2026-10-19, decided). An edit deletes the
turns that follow, never the files they produced or changed. The preview
panel lists the whole workspace.

**Voice is an audio attachment** (2026-10-19, decided). llama-server reports
`audio` among the model's modalities, and Strands sends `audio` blocks as
`input_audio`. The recording goes to the model as it is, with no
speech-to-text step and nothing to install.

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

**Benchmark baseline: 5/12** (2026-10-19, measured with a local benchmark kept out of the repo). Fails
are about quality, not plumbing: no date context, guessed URLs with no search
engine, the `web_fetch` summariser mangling tables, dropped images in long
copies, claimed-but-not-done steps, and giving up early with thinking off.
Phase 2 measures each change against this. See `docs/roadmap.md`.

**A search MCP mattered more than new tools** (2026-10-19, found by test).
With a filesystem and a DuckDuckGo search MCP installed, a search-save-verify
task ran cleanly in 5 calls, and the F1 task returned real, correct winners.
What remained was the date: the model read "last season" as 2024 because it
did not know the year. So `todo_write`, `notebook` and subagents are on hold.

**The date in the prompt, the time in the message** (2026-10-19, decided).
The system prompt carries today's date, which changes once a day, so
llama.cpp's prompt cache is kept. Each user message ends with
`[Sent Mon 19 Oct 2026, 18:38 (UTC+05:30)]`, which only the model sees.

**docx to PDF needs Word or LibreOffice** (2026-10-19). `docx2pdf` drives Word
over COM; without Word or LibreOffice the script says so and points the model
to read the document and `create_document` the PDF instead. xlsx to PDF has no
library that works without Excel, so it is not offered. `pdf2docx` (PDF to
Word) pulls in PyMuPDF, which is AGPL-licensed.

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

**One PDF reader, OCR per page** (2026-10-21, measured). `read_pdf.py`
reads the text layer where there is one and OCRs the rest: a page with
almost no text and a page-sized image is rendered and read; a large picture
on a text page is read and kept when it holds real text (at least 20
characters, mean confidence 0.75), so a diagram does not turn into "O O".
No second command: the model picks the first reader it sees. RapidOCR
(PaddleOCR models on onnxruntime, CPU, no Tesseract install) read a
synthetic scan and a table screenshot exactly, about 1.7 s a page; results
are cached beside the document's images, so a second read is instant
(0.24 s). The models download once on first use if missing.

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

**llama-server needs a per-launch API key** (2026-10-21, measured).
llama-server allows every origin, so any web page could call
`127.0.0.1:8080` and use the model. `atlas start` now generates a key per
launch (kept across restarts), passes it as `--api-key`, and gives it to the
backend in `ATLAS_LLAMA_KEY`. With it set, chat, `/props` and `/v1/models`
answer 401 without the key; `/health` stays open for the readiness check.

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

**Pairing guard** (2026-10-21). Host must be local; Origin must be the web UI
or an extension with the pairing token; cross-site requests without Origin
need the token. The extension needs no CORS: `host_permissions` lets it fetch
127.0.0.1 directly.

**WXT's `@` is its source folder** (2026-10-21, found). It overrides any user
alias, so the extension's `srcDir` is `client/src` and its entrypoints are
pointed back to `extension/`; shared components import `@/...` unchanged.

**PDFs by link** (2026-10-21, measured). `read_pdf.py` takes `http(s)://`
(downloaded into the workspace, reused on a second read; a web page instead
of a PDF fails with a hint) and `file://` (read in place). A message with a
PDF link gets the exact command, as attachments do: before, Gemma tried the
`read` tool on the URL and asked for an upload; after, one `read_pdf.py` call
and a correct answer. In the extension a PDF tab cannot be read by a content
script, so the panel attaches the PDF itself; tested on a scanned page.

**Images go to the model inside tool results** (2026-10-21, measured).
llama-server accepts an `image_url` part in a tool message: Gemma read
"Experiment No - 05" from a screenshot returned by a tool. So
`page_screenshot` / `page_image` hand the image straight back; through the
side panel it read a scanned circular correctly.

**Fill suggestions: one schema-constrained call, applied by the user**
(2026-10-21, measured). Not an agent turn: the form's fields and the user's
details go to the model once, with a JSON schema allowing only those field
ids and each select's options, "" when unknown. On an 8-field form it filled
7 correctly (a date converted to YYYY-MM-DD, "Sem 6" from "semester 6", the
pin code from the address) and left "Father's name" empty rather than
inventing it; 16 s. Never submits; secrets never collected.

**Fixes after the first real use** (2026-10-22). The mic had vanished: with
the parallel start, the backend asked llama-server for its modalities while
the model was still loading, got a 503 without them, and cached "none" for
the whole run; now only a real answer is remembered. Translate in the
selection chip never opened: the chip cancels mousedown to keep the page's
selection, which also stops a native `<select>`; it is a row of buttons now.
The "Save table" bar appeared over any table on hover, including Gmail's
account switcher (an ARIA grid); tables are now offered from the selection
chip inside a real data table, or the right-click menu.

**An Atlas PDF viewer for the extension** (2026-10-22). Content scripts cannot
run in the browser's PDF viewer, so PDFs had no highlights or chip. The
extension's own `viewer.html` (pdf.js with a text layer) is a page the panel
can read, search and highlight like any other; local PDFs come from the
backend so no file-access permission is needed.

**Tests stay out of the repository** (2026-10-19, decided). The user tests by
hand; the development tests and benchmark live in an ignored `tests/`.

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

## Windows

**Show the model `/c/Users/...` paths** (2026-10-18, found by test).
- Unquoted backslashes are escapes in bash, so `C:\Users\x` arrived as
  `C:Usersx`.
- The harness file tools reject any path not starting with `/`, so `read`,
  `write` and `edit` never worked on Windows.
- The Git-Bash form fixes both. MSYS converts it for native programs, and the
  sandbox converts it for Python's own file calls.

**`/tmp` is Git's, not `C:\tmp`** (2026-10-19, found by test). `web_fetch`
has curl write `/tmp/strands-web-fetch-*` and reads it back; that path was
resolved as `C:\tmp\...` and every fetch failed. POSIX paths go through
`cygpath`.

**Never `uvicorn --reload`** (2026-10-18). Its worker runs the Selector event
loop, which cannot start subprocesses on Windows. Every shell call failed with
an empty `NotImplementedError`, which reads like a broken script.

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

**One SQLite connection, WAL, closed on shutdown** (2026-10-18). A surviving
backend held `atlas.db` open, and deleting it gave `EBUSY`.

**The repository has two names** (2026-10-17). `Desktop\atlas-strands` is a
junction to `Desktop\atlas`.

---

## Paths and storage

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

**Skills are how documents are read** (2026-10-17). The harness `read` tool
does not help with rich documents on llama.cpp, and a 2B model writing
`python-docx` code is a bad bet, so each skill ships a script.

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
