# Client Subsystem: Next.js 16 + React 19 Frontend Interface

The `client/` directory contains the Next.js frontend for Atlas. It provides a real-time chat interface featuring Server-Sent Events (SSE) streaming, thinking/reasoning inspection, workspace terminal logs, session history, memory management, and system settings.

---

## Directory Architecture

```text
client/
├── app/
│   ├── integrations/page.tsx    # OAuth and service integrations (Gmail, etc.)
│   ├── memory/page.tsx          # Agent memory fact manager (CRUD for persistent user preferences)
│   ├── settings/page.tsx        # System settings editor (Model, runtime, tools, system paths)
│   ├── skills/page.tsx          # Skills catalog & install manager
│   ├── globals.css              # Tailwind CSS v4, theme variables, custom animations
│   ├── layout.tsx               # Root layout, Inter font, theme wrapper
│   └── page.tsx                 # Main chat canvas, streaming message bubbles, inline edit/retry
├── components/
│   ├── layout/
│   │   ├── app-layout.tsx       # Three-panel layout (Sidebar, Main Chat, Terminal Panel)
│   │   ├── sidebar.tsx          # Session history list, navigation, new chat, connection retry
│   │   ├── sidebar-item.tsx     # Navigation link item
│   │   └── terminal-panel.tsx   # Live execution logs viewer
│   ├── text-input/
│   │   ├── attachment-chip.tsx  # Uploaded file badge with image preview & remove button
│   │   ├── plus-menu.tsx        # File attachment trigger button
│   │   ├── profile-dropdown.tsx # Profile selector (redirects to /settings for profile config)
│   │   ├── text-area.tsx        # Auto-resizing textarea
│   │   └── text-input.tsx       # Main input bar: thinking budget, cloud switch, dual send/stop
│   ├── ui/                      # Base-UI primitives & Tailwind component wrappers
│   ├── markdown-renderer.tsx    # GFM markdown renderer with word-break safety
│   └── theme-provider.tsx       # Dark/light class toggler
├── lib/
│   └── utils.ts                 # Classname merge utility (clsx + tailwind-merge)
├── stores/
│   ├── chat-store.ts            # Active chat turn, SSE stream consumer, edit/retry runner
│   ├── session-store.ts         # Session CRUD, active session tracking, connection error banner
│   ├── text-input-store.ts      # Unsent prompt text, draft attachments, profile selection
│   └── ui-store.ts              # Sidebar open/close, terminal open/close, dark/light theme
├── next.config.ts               # Universal backend proxy rewrites (/api/:path* -> 127.0.0.1:8001)
├── package.json                 # Dependencies (React 19, Next 16, Zustand, Tailwind v4, Base-UI)
└── tsconfig.json
```

---

## State Management Architecture (Zustand)

### 1. `chat-store.ts` (Core Turn Runner & SSE Processor)
- **`Message` Interface**:
  - `status: "running" | "completed" | "cancelled" | "error"` (MANDATORY).
  - `content`: Pristine generated markdown (never polluted with system strings like `*Response was cancelled*`).
  - `thought`: Extracted reasoning tokens (from `<|agent_thought|>`).
  - `attachments`: List of `ChatAttachment` (`name`, `type: "image" | "document"`, optional `path`).
- **`processStream`**:
  - Reads SSE stream via `ReadableStreamDefaultReader` and `TextDecoder`.
  - Parses `data: ` payloads using `trimmed.slice(6).trim()`.
  - Dispatches by event type:
    - `meta`: Sets active `chat_id` in `session-store`.
    - `status`: Handles `running` (with label), `stopped` (sets `status: "cancelled"`), and `completed` (sets `status: "completed"`).
    - `thought`: Streams thinking text into `msg.thought`.
    - `chunk`: Streams generation text into `msg.content`.
    - `terminal`: Pushes log lines to `terminalLogs`.
    - `error`: Sets store error and marks message `status: "error"`.
- **Turn Actions**:
  - `sendMessage`: Appends `user` (`status: "completed"`) and `assistant` (`status: "running"`), sends `FormData` via `POST /api/chat`.
  - `stopGeneration`: Calls `AbortController.abort()`, calls `POST /api/chat/{id}/stop`, marks assistant `status: "cancelled"`.
  - `editMessage`: Preserves attachments, truncates UI history, dispatches `POST /api/chat/{id}/messages/{id}/edit`.
  - `retryMessage`: Resets assistant content to empty, sets `status: "running"`, dispatches `POST /api/chat/{id}/messages/{id}/retry`.

### 2. `session-store.ts` (Session Persistence)
- Manages `sessions: ChatSessionMeta[]` fetched from `/api/sessions`.
- Sets `sessionsError: "Unable to load chats"` on network failure, enabling the "Retry connection" button in `sidebar.tsx`.
- On deleting the currently active chat, calls `useChatStore.getState().resetChat()` to prevent stale messages from lingering on screen.

---

## Network Architecture & Universal Next.js Proxy

To eliminate CORS and preflight (`OPTIONS`) delays, `client/next.config.ts` proxies all `/api/*` requests directly to FastAPI:
```typescript
async rewrites() {
    return [
        {
            source: "/api/:path*",
            destination: "http://127.0.0.1:8001/api/:path*",
        },
    ];
}
```
- Client stores always use relative URLs (`const API_BASE = "/api"` or `/api/sessions`).
- Next.js streams chunked SSE byte streams without buffering.

---

## Rules for AI Agents Modifying `client/`
1. **Never Mutate Content for Statuses**: Never append strings like `*Response was cancelled*` to `msg.content`. Cancellation is tracked via `msg.status === "cancelled"` and rendered in the status slot.
2. **Action Bar Scoping**:
   - The user edit button must only be shown on `isLastUser && !isLoading`.
   - The assistant retry button must only be shown on `isLastAssistant && !isCancelled && !isLoading`.
   - Copy is allowed on any message with content.
3. **Strict Typing**: Do not use `any` in message mapping; use `Partial<Message>` or strict interfaces.
4. **No Hardcoded Backend Ports**: Never hardcode `8001` in components or stores. Use relative `/api/...` paths.