# extension/ — Atlas in the browser

A side panel for Edge and Chrome (Manifest V3, built with WXT). It is a second
UI on the same backend: the chat is the web UI's own components, and the
extension only adds what needs the browser. Design: `docs/extension.md`.

```
entrypoints/
  sidepanel/           Panel.tsx (which view; the tab a chat is attached to), components/ (PageCard,
                       PanelHome, HistoryView, QuoteSources, SettingsView, Centered), actions/ (bindPage,
                       pageCall, suggestFill, pdf), hooks/usePendingAsks.ts (chip and context-menu
                       questions), status.ts, url.ts
  content.ts           page operations in the tab (the chip comes from lib/ui/chip.ts)
  viewer/              the Atlas PDF viewer: pdf.js with a text layer, read / find / highlight
  background.ts        opens the panel; context menu; pairing; posts tables to the backend
lib/
  page/                the page layer, built in code from the live DOM (the model never sees HTML):
                       snapshot.ts (what goes with a message: a Google file, an article, or the tree),
                       ax.ts (the accessibility tree: roles and names from dom-accessibility-api,
                       refs like e12; never what the user typed: a typed field is only "filled"),
                       google.ts (Docs / Sheets / Slides through their exports; Drive file pages),
                       read.ts (an article via Readability and Turndown; a field's name and state),
                       tables.ts (rows with merged cells expanded), images.ts, highlight.ts (find
                       and highlight with the CSS Custom Highlight API, the page's DOM unchanged)
  fill/fill.ts         fill suggestions: fields out, preview over them, fill on Apply, never submit
  ui/                  chip.ts (Explain, Simplify, Define, Translate, Save table), overlay.ts (drawn
                       on the page in a shadow root)
  shared/              settings.ts (storage.local), tab.ts (calling the content script or the PDF
                       viewer), capture.ts (screenshots and page images for the model)
```

## Build and load

```
npm install
npm run build        # .output/chrome-mv3
npm run dev          # Edge with the extension loaded and hot reload
```

`edge://extensions` (or `chrome://extensions`), Developer mode, Load unpacked:
`extension/.output/chrome-mv3`. Then Connect, from the panel or from Atlas's
Browser extension page: the page posts `atlas:pair` with the token, the
content script (only on a local http page, only from that page's own window)
relays it to the background worker, which keeps it only if that address is the
one the extension is set to (default `http://127.0.0.1:8000`) and the backend
there accepts it. A page cannot change the address: another port is set in the
panel's Settings. The page learns whether it is connected, never more.
The token and address can still be typed under the panel's Advanced settings.

## Sharing the web UI

WXT always maps `@` to its source folder, so `srcDir` is `../client/src` and
`entrypointsDir` points back here; `@ext` is this folder's `lib/`. React,
React DOM and the Radix tooltip are deduplicated (`resolve.dedupe`) so the
panel and the shared components use one copy. Shared code must stay light:
pdf.js is the viewer's alone.

## How a page question works

1. When a message is sent, the content script takes the page's snapshot
   (`lib/page/snapshot.ts`, 5-150 ms on real pages) and it goes with the
   message, so the model answers in its first call: no tool call, no extra
   model turn, spent on reading. What it holds:
   - a Google Doc, Sheet (the open tab, as CSV) or Slides deck: its text, from
     Google's export, fetched in the page with the user's session (same origin);
     a Drive file page: the file is downloaded by the panel and attached;
   - an article (Readability's `isProbablyReaderable`): its text as Markdown,
     link words without addresses, then the page's links and controls;
   - anything else: the accessibility tree (`ax.ts`): headings, text, lists,
     tables (up to 200 rows), landmarks (menus and footers as one line of
     links), and every link, button and field as `[button: Submit](e12)`.
     Open shadow roots and same-origin frames are walked; each element keeps
     its ref across snapshots; hard caps (60k nodes, 1.5 s) so no page can
     hang the tab.
   - a question from the selection chip: only the section around the passage.
   The backend puts it after the user's text, marked as page content, taints
   the chat at once, saves a page over 12k characters to the workspace with
   its start inline, and does not send a page again that an earlier completed
   turn already carried unchanged (`page_hash` in the turn's stats).
   "Can read" on the page card turns all of this off for the chat.
2. The page tools stay for more: `page_find` (find and highlight),
   `page_show` (scroll to an element by its ref and outline it), `page_read`
   (read again after the page changed; "elements" lists only the refs),
   `page_screenshot`, `page_image`. A page tool emits `client_call`; the shared store hands it to the panel
   (`atlas.onClientCall`), which runs it in the tab's content script and POSTs
   the result to `/api/runs/{id}/calls/{call_id}`.
3. Page content is labelled untrusted, and once read, shell commands and
   writes outside the workspace need approval (`policy.py`, page taint).
4. Under the answer, the panel finds each quote on the page: found ones are
   highlighted (CSS Custom Highlight API) and clickable; missing ones are
   marked "not found on the page".

A PDF tab is different: the browser's PDF viewer runs no content script.
Two ways in:

- **Open in Atlas viewer** (the panel's button): the PDF reopens in
  `viewer.html`, an extension page with pdf.js and a text layer, where
  reading (page by page), find, highlights and the selection chip work as on
  a web page. A local `file://` PDF is served by the backend
  (`/api/extension/pdf`, PDFs only), so no "allow access to file URLs" switch
  is needed. The panel messages the viewer with `runtime.sendMessage` addressed
  to its tab id (extension pages get no tab messages).
- Otherwise the panel attaches the PDF to the chat's first message (fetched
  with the user's session; `file://` and fallbacks copied by the backend,
  `/api/chats/{id}/files/import`), and the pdf skill reads it, OCR included.

**Tables** are offered only on request: select text inside a real data table
and the chip adds xlsx / csv. "Real" is strict (`dataTable` in `lib/ui/chip.ts`): the
innermost `<table>`, not presentation, not in a menu, dialog or nav; a header
or 3+ rows; 2+ columns most rows agree on; short cells. There is no
right-click entry: a browser cannot show a menu item only over tables, so it
was on every page.

**Looking at images.** `page_screenshot` and `page_image` return the image in
the tool result (llama-server accepts images in tool messages); the panel
captures the tab or fetches the image with the user's session. The camera
button attaches a screenshot to the next message, and "Ask Atlas about this
image" on the right-click menu sends one image.

**Fill suggestions.** The Fill button sends the form's fields (labels,
types, options; never their contents) to `/api/extension/fill`. The backend
asks the model once, constrained by a JSON schema of those fields and their
options, against the user's details (`<data>/profile.md`, edited in Settings
> Browser extension and never readable by the extension). The values appear
over the fields with Apply / Discard; Apply sets them with input and change
events. The form is never submitted. Password, OTP, CVV, card and captcha
fields are never collected.

**History.** The clock button lists the browser's own chats (`source:
extension`), newest first, with their site; reopening one about another page
offers "Open that page" or "Use this tab", never silently reading a different
page. The last chat comes back when the panel reopens on the same page. All
chats, these included, are also in the web UI.

Nothing runs on sites in the never-read list; what the user typed into a field is never read.
