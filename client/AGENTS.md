# client/ — the web UI

React 19, Vite, Tailwind 3, Radix primitives, lucide icons, react-markdown
(with GFM, KaTeX and highlight.js). No chat framework: the components are our
own, modelled on llama.cpp's web UI (`tools/ui` in the llama.cpp repository).

```
npm install
npm run dev      # http://127.0.0.1:5173, proxies /api to the backend
npm run build    # type-check and build into dist/
npm run lint     # oxlint
```

`atlas start` runs `npm run dev` with `VITE_ATLAS_BACKEND_PORT` from
`settings.json`. Only `/api` is proxied, so `/settings`, `/skills` and `/mcp`
are the app's own pages.

```
src/
  App.tsx                    routes, sidebar, keyboard shortcuts, delete dialog
  lib/store.ts               the single source of truth (see below)
  lib/api.ts                 one function per backend route
  lib/types.ts               the API contract
  lib/transcript.ts          fold run events into parts (mirrors server/transcript.py)
  lib/prefs.ts               display preferences, per browser (theme, Enter sends, ...)
  lib/settingsSchema.ts      how settings.json is grouped on the Settings page
  lib/shortcuts.ts           the shortcut table, read by the handler and the Shortcuts page
  components/Sidebar.tsx
  lib/audio.ts               record the microphone; re-encode as 16 kHz mono WAV
  components/chat/           ChatScreen, Messages, Composer, MentionMenu, ContextGauge, Markdown, ToolBlock
  components/preview/        PreviewPanel, FileView (docx, pdf, xlsx, images, text)
  components/ui/kit.tsx      Button, Switch, Notice, PageShell, ...
  pages/                     SettingsPage, SkillsPage, McpPage
```

## The store (`lib/store.ts`)

Why the UI is fast, and the rules that keep it fast:

- **Subscribe to a slice.** `useAtlas(s => s.x)` re-renders a component only
  when `x` changes. A selector must return existing objects or primitives;
  building a new object in a selector re-renders forever.
- **One update per frame.** SSE events are buffered and folded once per
  `requestAnimationFrame`.
- **Only the live turn changes identity.** Rows are `memo`ised on their turn
  object; while one answer streams, no other row renders.
- **Markdown is split into blocks**, each memoised (`Markdown.tsx`). While
  streaming, only the last block is re-parsed.
- `seq` survives reconnects: the stream resubscribes with `after=seq+1`.

Send, retry and edit get the new chat view back from the POST, so the old
answer is replaced at once. Version switching (`<` `>`) moves the counter
optimistically, then takes the server's path.

## Matching llama.cpp

Taken from llama.cpp's source, not screenshots:

- **Palette:** `index.css`. shadcn "neutral" in oklch, with llama.cpp's darker
  light-mode border and darker dark background. Tokens are "L C H" triples so
  Tailwind opacity modifiers work (`bg-muted/60`).
- **Layout:**
  - floating rounded sidebar, 288px, collapsing to a 48px icon rail;
  - 48rem chat column;
  - "Hello there" greeting with the composer centred while empty.
- **Composer:** `INPUT_CLASSES`, pill radius, + menu, context gauge (20px ring,
  amber at 80%, red at 95%, details on hover), thinking switch, round send/stop
  buttons.
- **Messages:**
  - user bubble `bg-primary/5`;
  - assistant answers without a bubble;
  - always-visible action icons;
  - "Reasoning..." shimmer while streaming, collapsed when done;
  - stats badges ("N tokens", time, "X.XX t/s").
- **Inline edit:** the composer replaces the message in place. Escape cancels.
- **Settings search** filters every field across all sections.
- **Shortcuts:** Ctrl/⌘ + K search, B sidebar, Shift+O new chat, Shift+E rename,
  Shift+S export, Shift+D delete, Shift+↑/↓ previous/next chat, `,` settings.

Where Atlas differs on purpose:
- Branding is text, with no logo.
- The thinking control is on/off, not effort levels.
- There is no per-message delete: an edit already rewrites history from that
  point.
- Regenerate appears on the last answer only.
- Skills and MCP are full pages.

Settings are ordered by what changes results most: Agent, Skills & MCP,
Access, Model; Recovery & context, Generation, and Server & storage are under
Advanced. "Restart now" appears at the top of Settings only when saved settings
wait for a restart or the last restart failed; it applies a new model or any
other restart setting, and a notice shows on every page while it runs.

Control: Settings > Access holds the allowed folders, whether to ask outside
them, and the approval timeout. The MCP page sets each tool On / Ask / Off.
Approval cards in the chat are titled by kind (install, access, tool). The
Skills page shows each requirement as installed or missing, with one button
for the missing ones.

## Working with files

- **Download chips** under an answer list the files that turn created or
  changed. Preview opens the panel; Download saves.
- **The preview panel** (right side, resizable) renders a workspace file:
  docx with `docx-preview`, pdf with pdf.js (canvas plus a text layer), xlsx
  from the backend's sheet preview, images, and text. Its file menu lists the
  whole workspace, so documents from turns that an edit removed are still
  reachable. `?preview=<file>` in a chat URL opens it directly.
- **Selecting text** in the panel offers "Ask about this": the passage goes to
  the composer as a quote chip and is sent as a `ref`.

## The composer

- **`@`** opens a menu of this chat's files (picking one attaches it), skills,
  tools and connected MCP servers (inserted as `@name`).
- **Voice**: the mic appears when the message box is empty and llama-server
  reports audio input. The recording is attached as a WAV, not transcribed.
- **Scrolling**: a new run brings its question to the top and the answer grows
  below. Following the stream is the "Auto-scroll while generating"
  preference, off by default.

Headless screenshots (`msedge --headless --screenshot`) use a virtual clock
that does not run web workers, so pdf.js never finishes there. Drive the
browser over DevTools with real waiting instead.

## Adding a setting to the UI

Add the key to `agent/core/settings.py` (and `TIERS`). It appears under
Storage → Other with a generic control straight away. To place it in a section
with a label, help text and a proper control, add a `Field` to
`lib/settingsSchema.ts`. RESTART-tier keys get the "restart" badge
automatically.
