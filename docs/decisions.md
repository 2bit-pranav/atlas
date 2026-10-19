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
