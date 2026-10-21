# Browser extension

A side panel in Chrome and Edge that lets Atlas see and help with the page
the user is on. It is a second UI on the same backend: the extension never
runs tools itself, it shows a chat and carries page operations between the
backend and the tab.

Status: version 1 built, 2026-10-21: Milestone 1 except "clip to notes",
for Edge and Chrome. See `extension/AGENTS.md`. As built: answers quote the
page in double quotes and the panel highlights each quote (or marks it as not
found) under the answer; `page_find` highlights and scrolls for "where does it
say X?". Two page tools only, `page_read` and `page_find`.

---

## Why an extension, and not a browser for the model

Giving a 2B model a browser and a whole task (navigate, find, fill, submit)
fails too often to be a product. General browser MCPs make it worse: a couple
of dozen tool schemas, an accessibility snapshot of the whole page after every
action, and short-lived element ids the model must copy back.

The extension takes the other approach: **the human drives, Atlas helps.**
The user's own browser already has their logins, shows whatever is on screen,
and has a person present for captchas, odd navigation and anything risky. The
model does what a small model does well: read, find, extract, map values onto
fields, draft.

## Extension or web UI

Each has a different subject:

- **Extension: the page you are on.** Short, in-context help: read it, find
  something in it, take something out of it, fill something into it.
- **Web UI: your work.** Files, documents, long sessions, and managing Atlas.

The test for a feature: does it start from a web page? Then it belongs in the
extension. Is it about files or Atlas itself? Then the web UI.

What stays in the web UI:

- Long work on documents, with the preview panel and the workspace files.
- The chat tree: versions, retry, editing earlier turns.
- Skills, MCP servers, settings and access folders.
- Automations, later: reviewing recordings, run history, unread runs.
- All chat history, including extension chats, grouped by site.

**Continue in Atlas** moves an extension chat to the web UI with the page
attached, for when a quick question turns into real work.

The extension has the **full toolset** (every enabled skill and MCP tool),
since the backend runs the agent. What it lacks is *management*: no
installing skills or servers, no settings beyond its own few (below).

---

## Features

### Milestone 1

1. **Answers with highlights.** Ask about the page; every claim in the answer
   links to a highlighted passage, and clicking it scrolls there. For a 2B
   model this is also a trust feature: a highlight that does not support the
   claim is visible at once.
2. **Selection chip.** Select text and a small button offers explain,
   simplify, define or translate (Gemma is multilingual: Hindi, Marathi, ...).
   Also on the right-click menu as "Ask Atlas".
3. **Table to spreadsheet.** Click any table and save it as xlsx or csv into a
   chosen folder. Extraction is code reading the DOM; `create_document` writes
   the file. No model in the path.
4. **Clip to notes.** Save the page, a selection or a summary as Markdown into
   a folder such as `Study/`, with the source link. Over time a local,
   searchable notes folder the web UI can read.
5. **Page plus your files.** The thing cloud assistants cannot easily do,
   because the files are on this machine:
   - a job or internship post: "compare this with my resume";
   - an assignment brief: "which of my notes cover this?";
   - a form: "find my roll number and ABC ID in my documents".

### Milestone 2

6. **Read images and screenshots.** Gemma's vision on the visible tab
   (`chrome.tabs.captureVisibleTab`) or one image. College notices,
   timetables and circulars are often images or scanned PDFs.
7. **Ask about a PDF link.** The extension fetches the PDF into the chat's
   workspace and the pdf skill reads it. Content scripts cannot reach the
   built-in PDF viewer, so this is the only way in.
8. **Compare tabs.** Pick 2-3 open tabs (products, colleges, train results)
   and get a comparison table. Read only.
9. **Fill suggestions.** Values come from a local profile file. Atlas shows
   them as a preview overlay; the user clicks Apply. **It never submits.** The
   model's job is mapping profile values onto the form's labels, constrained
   by a JSON schema to the labels actually on the page.
10. **Draft in a text box.** Focus any text area (email reply, forum post, an
    application's "why us" field) and get a draft based on the page, inserted
    for the user to edit.

### Human-pair, as a ladder

| Tier | What Atlas does | Example |
|---|---|---|
| Read | Reads and reasons; the user drives | User searches trains on IRCTC; Atlas filters the results ("3AC, arrives before 9 am, cheapest first") |
| Suggest | Proposes values; the user applies | Fill suggestions, drafts |
| Act | Clicks and navigates, one step at a time, user can take over | Later, gated on the fixture benchmark |

IRCTC and similar sites are good *read* demos and bad automation targets:
captcha at login, aggressive bot protection, terms that forbid automation.

### Trust and privacy

- **Works on private pages.** College portal, bank statement, medical report:
  pages nobody would paste into a cloud chatbot. Nothing leaves the machine.
- **Site controls.** A never-read list (banking and the like), and a visible
  chip showing exactly what Atlas can see on the current page.
- **No password values**, ever. Other field values only when the task is
  about that form.

### Extension settings

Only three; everything else links to the web UI:

- the clips folder;
- the profile file used for fill suggestions;
- the site list (never read / always ask).

---

## Architecture

```
side panel (React)  ──HTTP + event stream──  backend (FastAPI, Strands)
      │                                            │
      │  chrome.runtime messages                   │ page tool called
      ▼                                            ▼
content script (page layer)  ◄── page_request ── run emits event
      │                                            ▲
      └──────────── result POSTed back ────────────┘
```

### Client calls

The round trip already exists: approvals. A run emits `approval_request`, the
UI answers, a future resolves. Page tools work the same way:

1. The agent calls a page tool (`page_read`, `page_find`, ...).
2. The run emits `page_request {call_id, tab_id, op, args}`.
3. The side panel forwards it to the tab's content script.
4. The result is POSTed to `/runs/{id}/calls/{call_id}`; the future resolves;
   the tool returns.

Generalise `Run.approvals` into client calls: same future, same timeout, same
"cancelled run denies everything". Page tools are added to the turn's toolset
only when the chat is attached to a tab. Strands, policy and recovery do not
change.

### Pairing and CORS

Once the backend accepts calls from an extension, **any website can also call
`127.0.0.1:8000`**. So, before any other extension work:

- `atlas start` generates a pairing token (stored in `.data/`). The user
  pastes it into the extension once.
- CORS allows only the extension's origin (and the web UI's own origin).
- Every request carries the token. `EventSource` cannot send headers, so the
  event stream takes it as a query parameter, or `streamRun` moves to a
  `fetch` stream.

Serving the built web UI from the backend (see the CLI cleanup) puts it on the
API's own origin, which leaves the extension as the only cross-origin caller.

### Chats

- `chats.source`: `web`, `extension` (later `automation`). The web UI groups
  by it.
- Extension chats store the tab's URL and title, so the web UI can show which
  page a chat was about and group by site.
- A chat is attached to one tab. Switching tabs offers a new chat or
  re-attaching, never silently reads a different page.

---

## Reusing the UI

What `client/` already has, sorted:

| Shared | Web only | Extension only |
|---|---|---|
| `lib/`: `api.ts`, `types.ts`, `transcript.ts`, `time.ts`, the store's chat and run logic | `Sidebar`, `ChatScreen` layout | Page chip |
| `Messages`, `Markdown`, `ToolBlock`, `Composer`, `MentionMenu` | `PreviewPanel`, `FileView` | Quick actions |
| `ui/` kit, Tailwind config, tokens in `index.css` | Settings, MCP, Skills pages | Highlight renderer, fill preview |

Setup: keep `client/` as it is. The extension (built with **WXT**, which
handles the MV3 manifest, side panel entry and content scripts on Vite)
imports through an alias, `@atlas/ui -> client/src`. Move shared code into a
workspace package only if the alias starts to hurt.

Three changes to the shared code:

1. **Injectable base URL and token in `api.ts`.** `request()` and
   `streamRun()` take them from config instead of assuming the page's origin.
2. **No heavy libraries in shared components.** `pdfjs-dist` and
   `docx-preview` are the preview panel's and must not be imported by shared
   code. KaTeX and highlight.js load lazily.
3. **Work at ~360px.** `ToolBlock` and Markdown tables are the likely
   problems; a `compact` density prop is usually enough.

The side panel is its own extension page, so host-page CSS cannot reach it.
Only what is drawn **on** the page (selection chip, highlights' popovers, fill
preview) needs isolating: render it in a shadow root, in vanilla JS or Preact,
not the React app.

---

## The page layer

**The model never sees HTML.** One content-script module reads the live DOM
in code and produces three compact views. Obfuscated class names
(`css-1x7kq2b`, hashed CSS modules) do not matter, because classes are never
used.

The same module will later be injected by Playwright for headless runs, so the
extension and unattended automations share one implementation.

### 1. Readable text: questions and summaries

- Mozilla **Readability** on a clone of the DOM, then **Turndown** to
  Markdown. Navigation, ads and footers drop out; a typical article is a few
  thousand tokens.
- No article found (dashboards, portals, web apps): the visible text of the
  main region, grouped by headings.
- **Long pages go to a file** in the chat's workspace. The model gets an
  outline (headings plus each section's first line) and a search tool: the
  same pattern as `read_pdf --search`.

### 2. Element list: filling and acting

Built from accessibility information:

```
Form "Student details"
  textbox "Full name" (empty)
  textbox "Roll number" = "21CS045"
  combobox "Semester" options: Sem 1 ... Sem 8
  button "Submit"
```

- **Role** from the tag or `role` attribute.
- **Name** from `aria-label`, an associated `<label>`, placeholder, visible
  text, `title`, `alt`.
- **Visible only**: `getBoundingClientRect` and computed style; `aria-hidden`
  is skipped.
- Capped (about 40), de-duplicated, grouped by form, menu or region.
- Weak spot: clickable `<div>`s with no role. Heuristic: `cursor: pointer`,
  `tabindex`, an `onclick` attribute.

The model refers to elements by **name** (`fill "Roll number"`). The content
script keeps a numbered map from the latest snapshot to the real elements and
resolves names in code, with fuzzy matching. Two matches return a short list to
choose from rather than a guess. Labels are stable between snapshots; the
model never copies an id.

After an action, the result is a short diff (URL changed, menu opened, field
enabled, download started), not the page again.

Mechanics that live in code, not in the model's reasoning:

- clicking a hidden menu link hovers its ancestors first (hover-only navbars);
- `select` waits for dependent fields to enable or reload their options;
- new tabs are followed; downloads are named in the result;
- cookie banners and `alert` dialogs are dismissed.

### 3. Tables: data

`<table>` elements, and `div` grids with `role="grid"`/`row`/`cell`, become
rows in code, with `colspan`/`rowspan` expanded. They are saved straight to
xlsx or csv. The model sees the header and the row count unless it asks for
more.

### Highlights

The reverse direction. The model returns a quoted phrase; code walks the
page's text nodes (`TreeWalker`) with whitespace normalised and a little fuzzy
matching, builds a `Range`, and marks it with the **CSS Custom Highlight API**
(`CSS.highlights`). Nothing in the DOM changes, so React-heavy pages do not
break.

### Edge cases

| Case | Handling |
|---|---|
| Single-page apps | Fresh snapshot each time one is asked for; a `MutationObserver` marks the old one stale |
| Shadow DOM | Walk open shadow roots |
| Iframes | `all_frames: true`; each frame's content script reports back |
| Canvas-rendered pages (Google Docs, Flutter) | No DOM text: screenshot plus vision |
| Built-in PDF viewer, `chrome://`, Web Store | Content scripts cannot run there. PDFs are fetched by URL instead |

---

## Security

### Prompt injection

Page text flows into an agent that has `shell`, file writes and installs, and
a 2B model follows instructions it reads. So:

- Page content is wrapped and labelled as untrusted data in every tool result.
- A new `ToolPolicy` step, **page taint**: once page content is in the turn,
  `shell`, writes outside the clips folder, and installs require approval,
  whatever the usual setting.

This is the same hook as the existing access, install and sensitive steps.

### Downloads

Chrome lets an extension save only inside the user's Downloads folder. Files
go to `Downloads/Atlas/<chat id>/`, and `Downloads/Atlas` is added to the access
scope, so the backend treats them like attachments.

---

## Milestones

### Milestone 1

In this order; each depends on the one before.

1. Pairing token and CORS lockdown.
2. Side-panel chat from the shared components; `chats.source`.
3. Client calls (generalised `Run.approvals`).
4. `page_read`: readable text, element list, long pages to a file.
5. Find and highlight.
6. Page-taint policy step.
7. Selection chip, table to spreadsheet, clip to notes, page plus files.

**Done when:**

- on a long real page, "where does it say X?" scrolls to and highlights the
  right passage;
- a page containing shell-command instructions cannot run a command without
  approval;
- a results table on a real site saves as a correct xlsx.

### Milestone 2

Vision on screenshots and images, PDF links, compare tabs, fill suggestions,
drafting in text boxes.

### Testing

A local **fixture site** for the benchmark, served by the backend: a long
article, a hover-only menu, ASP.NET-style dependent dropdowns with a delay, a
link that opens a new tab, a download, a results table with merged cells, a
cookie banner, and a page with injected instructions. Deterministic, unlike
real sites.

---

## Later: automations

Out of scope for the extension's first milestones; recorded here so the
design leaves room.

- **Recording is invoked**, never ambient: Record, Pause, Stop, then a review
  screen to delete stray steps and mark parameters.
- **Browser steps only** at first. A recorded macro replays to a file in the
  workspace (`/download-results`). A follow-up prompt template can run as an
  ordinary turn afterwards.
- `run_web_macro(name, params)` as a tool, with saved macro names as an enum.
  For automations, the runner calls the macro itself before the agent's turn.
- **Guards**, not compiled branches, for pages that may or may not appear
  (a sign-in, a cookie banner): handlers that run when a page matches.
- **Google**: public content is fetched by URL (a Drive file shared "anyone
  with the link" is a plain HTTP download, e.g. with `gdown`); private content
  goes through the API with OAuth via MCP; never a recorded Google sign-in on
  a schedule.
- Headless runs use Playwright with the same page-layer module.

---

## Open questions

- WXT or CRXJS: check which handles the React 19 / Vite 8 setup with less
  friction.
- Where the profile file for fill suggestions lives, and its format.
- Whether the never-read list ships with defaults (banks, payment pages).
- Firefox: its sidebar differs from Chrome's side panel API. Chromium first.
