# extension/ — Atlas in the browser

A side panel for Edge and Chrome (Manifest V3, built with WXT). It is a second
UI on the same backend: the chat is the web UI's own components, and the
extension only adds what needs the browser. Design: `docs/extension.md`.

```
entrypoints/
  sidepanel/Panel.tsx  pairing, the tab a chat is attached to, quote sources, chip questions, settings
  content.ts           page operations, the selection chip, "Save table"
  background.ts        opens the panel; context menu; posts tables to the backend
lib/
  page.ts              the page layer: readable Markdown, element list, tables, find, highlight
  overlay.ts           what is drawn on the page (shadow root, plain DOM)
  tab.ts               calling the content script (injects it into tabs opened before install)
  settings.ts          the extension's settings (storage.local)
```

## Build and load

```
npm install
npm run build        # .output/chrome-mv3
npm run dev          # Edge with the extension loaded and hot reload
```

`edge://extensions` (or `chrome://extensions`), Developer mode, Load unpacked:
`extension/.output/chrome-mv3`. Pair it with the token from Atlas > Settings >
Browser extension.

## Sharing the web UI

WXT always maps `@` to its source folder, so `srcDir` is `../client/src` and
`entrypointsDir` points back here; `@ext` is this folder's `lib/`. React,
React DOM and the Radix tooltip are deduplicated (`resolve.dedupe`) so the
panel and the shared components use one copy. Shared code must not import the
preview panel's heavy libraries.

## How a page question works

1. The panel sends the message with the attached tab's URL and title; the
   backend adds `page_read` and `page_find` for that turn.
2. A page tool emits `client_call`; the shared store hands it to the panel
   (`atlas.onClientCall`), which runs it in the tab's content script and POSTs
   the result to `/api/runs/{id}/calls/{call_id}`.
3. Page content is labelled untrusted, and once read, shell commands and
   writes outside the workspace need approval (`policy.py`, page taint).
4. Under the answer, the panel finds each quote on the page: found ones are
   highlighted (CSS Custom Highlight API) and clickable; missing ones are
   marked "not found on the page".

A PDF tab is different: the browser's PDF viewer runs no content script. The
panel attaches the PDF to the chat's first message instead (fetched here with
the user's session; `file://` and fallbacks copied by the backend,
`/api/chats/{id}/files/import`), and the pdf skill reads it, OCR included.

Nothing runs on sites in the never-read list; password values are never read.
