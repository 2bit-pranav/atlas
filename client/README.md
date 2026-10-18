# Atlas client

React + Vite + Tailwind, with [`@assistant-ui/react`](https://assistant-ui.com)
for the chat surface.

## Running it

The client needs the backend. Start that first — `atlas up` from the repository
root starts llama-server, the backend, and this Vite client:

```
atlas start        # in the repository root
```

Then open http://localhost:5173.

| | port | where |
|---|---|---|
| model (llama-server) | 8080 | spawned by `atlas start` |
| backend (FastAPI) | 8000 | spawned by `atlas start` |
| client (Vite) | 5173 | spawned by `atlas start` |

## How it talks to the backend

The backend serves its routes at the **root**, not under a prefix. `vite.config.ts`
proxies each of the six prefixes it uses to 8000:

```
/health  /chats  /turns  /runs  /settings  /skills
```

So requests go to the same origin the page was served from — no CORS, no
`VITE_ATLAS_API` needed in development. Set `VITE_ATLAS_API` only when pointing
at a backend on another host; leave it empty otherwise.

Proxied rather than called cross-origin for two reasons: the backend sends no
CORS headers, and `GET /runs/{id}/events` is a long-lived SSE response that a
browser will not open to another origin at all.

## Where things are

```
src/types/api.ts              the backend contract, transcribed. One file, so a
                              backend change breaks here and nowhere else.
src/services/atlasApi.ts      one function per route. No retries: a retried POST
                              is a duplicated turn.
src/services/atlasStore.ts    owns the SSE projection — what is true.
src/services/atlasRuntime.ts  hands that projection to assistant-ui as an
                              ExternalStoreAdapter — what it looks like.
src/components/chat/          Reasoning.tsx, ToolCard.tsx, Composer.tsx,
                              ChatSurface.tsx, WelcomeScreen.tsx
src/components/settings/      a generic renderer over GET /settings + PUT.
```

The division matters: `atlasStore` owns the streaming, resumption and chat-tree
logic; assistant-ui owns the chat UX. Nothing else keeps a parallel copy of the
messages, because two copies of a streaming answer drift apart within a second.

## Two things that will bite if you change this

* **`?after=` is an inclusive start index.** The server does `events[after]`
  first, which is also why its default is `0` rather than `-1`. Resuming after the
  last event handled means sending `after=lastSeq + 1`; sending `after=lastSeq`
  replays it. The store does this and *also* drops any `seq` it has already seen,
  so a change in that semantic costs one ignored frame rather than a duplicated
  sentence.
* **`created_at` is already in milliseconds.** The backend stores
  `time.time() * 1000` and serves it unchanged. Multiplying by 1000 puts every
  message in the year 58000.

## Settings

`AtlasSettings` from the old demo engine is gone. There is no flat
`{llamaCppUrl, selectedModel, temperature}` object and no model picker: the only
model is the one in `settings.json`, and the modal renders whatever
`GET /settings` returns. RESTART-tier keys are shown disabled with the reason on
them, because a setting you cannot find is worse than one you can see but cannot
reach. `memory.enabled` is locked and shows the backend's own reason, because that
reason is the entire basis on which branch isolation currently holds.

## Building

```
npm run build     # tsc -b, then vite build
npm run lint      # oxlint
```

The bundle is ~880 kB (~270 kB gzipped), most of it assistant-ui. Not split yet;
worth doing if first paint on the local model ever feels slow, which it should
not — the model is the slow part.
