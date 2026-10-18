# Client plan: connecting `client/` to the Atlas backend

Written 2026-10-17. Nothing in `client/` has been changed yet.

## Two facts that settle the open questions

**`.agent/` is already where you want it.** Strands writes it relative to the
process working directory, and the backend runs from the atlas root, so it lands
at `atlas/.agent/sessions/`. Nothing to configure. The only stray is
`tests/.agent/` â€” leftovers from the branch-leak probes, which must be deleted
and gitignored so the leak evidence cannot be committed again.

**`@assistant-ui/react` is already in `package.json`.** No library search is
needed. It is the right choice: it gives message threading, the composer,
markdown rendering and tool-call rendering out of the box, and it accepts an
*external store*, which is exactly our situation â€” we own the transport, it owns
the chat UX.

## What is wrong with the current client

| File | Problem |
|---|---|
| `services/agentEngine.ts` | Mock engine with demo workflows. No HTTP at all. |
| `config/models.ts` | **Fictional models** â€” Llama 3.3 70B, Qwen 2.5, Mistral Nemo, DeepSeek R1. None of these files exist on this machine. |
| `types/chat.ts` | `AtlasSettings` is flat (`llamaCppUrl`, `selectedModel`). Ours is dotted keys plus LIVE/RESTART tiers. |
| `components/chat/AgentWorkflowThinking.tsx` | The demo workflow being removed. |
| `components/settings/SettingsModal.tsx` | Built for the flat shape. Cannot express tiers or a 409. |
| `App.tsx` | 15KB wired to the mock engine's invented shapes. |

## Decisions taken

- **Model picker: delete the mock models entirely.** Show only `model.path` and
  `model.context_size` from `GET /settings`. If the model is set to restart tier,
  display it read-only and say it needs a restart â€” it cannot be changed live.
- **Settings: everything editable.** Every key in `values` is editable, except
  RESTART-tier keys, which are shown disabled with a "restart required" hint and
  a `PUT` that returns 409 if attempted anyway. A `pending_restart` banner shows
  when a RESTART key differs from what the servers were launched with.
- **Event UI is kept, not removed.** The components stay; only their *data
  source* changes â€” from invented `thinkingSteps[]` to our real event stream.
  Tool activity, thinking deltas and token usage all render as they arrive.

## Step 1 â€” the contract (`src/types/api.ts`)

Rewrite `types/chat.ts` against the real backend. Nothing else can be built
until this is right, so it goes first and alone.

```ts
export type Tier = "live" | "restart"

export interface SettingsView {
  values: Record<string, unknown>     // flat dotted keys, e.g. "sampling.temperature"
  tiers: Record<string, Tier>
  pending_restart: Record<string, unknown>
  tools: { groups: Record<string, boolean>; builtin_tools: string[]; interventions: boolean }
  memory: { enabled: boolean; reason: string }
  skills: { name: string; description: string; scripts: string[] }[]
}

// Exactly what server/events.py emits.
export type RunEvent =
  | { seq: number; type: "run_started"; chat_id: string; turn_id: string }
  | { seq: number; type: "thinking_delta"; text: string }
  | { seq: number; type: "text_delta"; text: string }
  | { seq: number; type: "tool_start"; id: string; name: string; args: unknown }
  | { seq: number; type: "tool_args_delta"; id: string; name?: string; args: unknown }
  | { seq: number; type: "tool_end"; id: string; name: string; status: string; text: string }
  | { seq: number; type: "usage"; input: number; output: number; total: number; reported?: number }
  | { seq: number; type: "done"; status: string }
  | { seq: number; type: "error"; status?: string; message: string }

export interface TurnView {
  id: string
  user_text: string
  files: unknown[]
  status: "running" | "completed" | "failed" | "cancelled" | "interrupted"
  created_at: number
  snapshot: string | null
  version: number
  version_count: number
}
```

## Step 2 â€” the runtime adapter (`src/services/atlasRuntime.ts`)

One file, replacing `agentEngine.ts`. An assistant-ui `ExternalStore` that
talks to our 20 routes.

- `POST /chats`, `GET /chats`, `GET /chats/{id}` â€” sessions and the visible path
- `POST /chats/{id}/files` â€” multipart upload; returns `path`, never parsed
- `POST /chats/{id}/messages` â€” returns `{run_id, turn_id}` immediately
- `GET /runs/{id}/events?after=<n>` â€” **SSE**, resume by last `seq`
- `POST /turns/{id}/retry` Â· `/edit` Â· `/select` â€” the tree operations
- `POST /runs/{id}/cancel`
- `GET`/`PUT /settings`, `GET /skills`, `GET /health`

**The SSE rule that must not be got wrong:** the client keeps the highest `seq`
it has seen and re-subscribes with `?after=<that seq>`. Reconnection must
produce no gaps and no duplicates â€” the server side is already tested for this,
so the client is the remaining half. A dropped connection is normal, not an
error state.

## Step 3 â€” remove the demo

Delete outright: `AgentWorkflowThinking.tsx`, `config/models.ts`, the
`previewData` / `thinkingSteps` fields, and every mock id in `App.tsx`.

Keep and rewire: `MessageItem`, `InputBox`, `Sidebar`, `AttachmentCard`,
`WelcomeScreen`. Their styling stays; only the props change.

## Step 4 â€” settings modal

Rewrite against `SettingsView`. Group by top-level key. Disable RESTART keys and
show why. Surface `pending_restart`. `memory.enabled` is not editable at all â€”
the backend rejects it, and it should be visibly locked with its reason, since
that reason is the whole reason branch isolation currently holds.

## Step 5 â€” model display

Read `model.path` / `model.context_size` from settings. No picker, no dropdown,
no fabricated list.

## Step 6 â€” verify against the live backend

With llama-server on 8080 and the backend on 8000: send a message, watch thinking
and tool activity stream in, cancel mid-run, retry, edit, walk `<`/`>`, change a
LIVE setting and see it take effect on the next turn, confirm a RESTART key is
refused.

## Also outstanding (backend, not client)

Three bugs block the xlsx skill from producing a correct answer through the real
model, in the order the model hits them:

1. `python` on `cmd`'s PATH is the **system** Python, not the venv, so
   `duckdb` is missing â†’ `ModuleNotFoundError`
2. the model then runs `pip install duckdb` to patch its own environment
3. the scripts do not tolerate Windows quoting: a quoted path arrives with its
   quote characters, and `cmd` does not treat `'...'` as quoting so SQL splits
   on spaces

Fix 1 and 2 together by having the SKILL.md name the exact interpreter path
(from `sys.executable`) rather than `python`, and fix 3 in
`skills/_shared.py::resolve`.

**Also not built:** the xlsx **write/edit** scripts, and the pdf and docx skills
untested against the real model.