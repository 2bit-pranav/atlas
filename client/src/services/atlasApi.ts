/**
 * HTTP client for the Atlas backend.
 *
 * Thin on purpose: one function per route, no caching, no retries, no state.
 * Everything that has to be right under changing conditions -- SSE resumption,
 * cancellation, run tracking -- lives in `atlasStore.ts`, where it can be seen
 * all at once. A client that silently retries a POST would be the worst possible
 * place to hide that behaviour, because a retried send is a duplicated turn.
 */

import {
  ApiError,
  type ChatFile,
  type ChatListItem,
  type ChatView,
  type RunEvent,
  type RunRef,
  type RunView,
  type SettingsView,
  type StoredMessage,
  type TurnView,
} from "@/types/api"

/**
 * Empty in dev, so requests go through Vite's proxy and the browser never hits
 * a cross-origin preflight. Set `VITE_ATLAS_API` for a backend on another host.
 */
const BASE = (import.meta.env.VITE_ATLAS_API as string | undefined) ?? ""

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers:
        init?.body instanceof FormData
          ? init?.headers
          : { "Content-Type": "application/json", ...init?.headers },
    })
  } catch (cause) {
    // fetch only rejects on a transport failure, so this is always "no backend".
    throw new ApiError(
      `cannot reach the Atlas backend at ${BASE || "the dev server origin"}.
Is it running on port 8000?`,
      0,
    )
  }
  if (!response.ok) {
    throw new ApiError(await describe(response), response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Prefer FastAPI's `detail`, which is the message the backend wrote for us. */
async function describe(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body?.detail === "string") return body.detail
    if (body?.detail) return JSON.stringify(body.detail)
  } catch {
    /* fall through to the status line */
  }
  return `${response.status} ${response.statusText}`
}

// ----------------------------------------------------------------- health --

export interface HealthView {
  status: string
  active_run: string | null
  runs_known: number
}

export const health = () => request<HealthView>("/health")

// ------------------------------------------------------------------ chats --

export const listChats = () => request<ChatListItem[]>("/chats")

export const createChat = (title = "") =>
  request<{ id: string; title: string }>("/chats", {
    method: "POST",
    body: JSON.stringify({ title }),
  })

export const getChat = (chatId: string) =>
  request<ChatView>(`/chats/${chatId}`)

export const deleteChat = (chatId: string) =>
  request<{ deleted: string }>(`/chats/${chatId}`, { method: "DELETE" })

export const getTurn = (chatId: string, turnId: string) =>
  request<{ turn: TurnView & { chat_id: string }; messages: StoredMessage[] }>(
    `/chats/${chatId}/turns/${turnId}`,
  )

// ------------------------------------------------------------------ files --

/**
 * Upload is multipart and the backend parses nothing (design.md principle 3):
 * it saves the bytes under the chat directory and the model reads the file on
 * demand through a skill. The returned `path` is what goes in the prompt.
 */
export async function uploadFile(
  chatId: string,
  file: File,
): Promise<ChatFile> {
  const form = new FormData()
  form.append("file", file, file.name)
  return request<ChatFile>(`/chats/${chatId}/files`, {
    method: "POST",
    body: form,
  })
}

export const downloadUrl = (chatId: string, name: string) =>
  `${BASE}/chats/${chatId}/files/${encodeURIComponent(name)}`

// ------------------------------------------------------------------- runs --

export const sendMessage = (
  chatId: string,
  body: {
    text: string
    files?: ChatFile[]
    thinking?: boolean | null
  },
) =>
  request<RunRef>(`/chats/${chatId}/messages`, {
    method: "POST",
    body: JSON.stringify({
      text: body.text,
      files: body.files ?? [],
      thinking: body.thinking ?? null,
    }),
  })

/** A retry is a new sibling with the same restore point, so the state is kept. */
export const retryTurn = (turnId: string) =>
  request<RunRef>(`/turns/${turnId}/retry`, { method: "POST" })

/** An edit is also a sibling. The original version stays on disk. */
export const editTurn = (turnId: string, text: string) =>
  request<RunRef>(`/turns/${turnId}/edit`, {
    method: "POST",
    body: JSON.stringify({ text }),
  })

/** Move among a turn's versions. `delta` is -1 for `<` and +1 for `>`. */
export const selectTurn = (turnId: string, delta: number) =>
  request<{
    turn_id: string
    snapshot: string | null
    versions: string[]
  }>(`/turns/${turnId}/select`, {
    method: "POST",
    body: JSON.stringify({ delta }),
  })

export const getRun = (runId: string) => request<RunView>(`/runs/${runId}`)

export const activeRun = () =>
  request<{
    run: { id: string; chat_id: string; turn_id: string; status: string } | null
  }>("/runs/active")

export const cancelRun = (runId: string) =>
  request<{ cancelling: boolean; status: string }>(`/runs/${runId}/cancel`, {
    method: "POST",
  })

// ---------------------------------------------------------------- settings --

export const getSettings = () => request<SettingsView>("/settings")

/**
 * Update LIVE keys. Sends only what changed, because the backend refuses the
 * whole request with a 409 if any RESTART key appears -- so a stale copy of one
 * disabled field must not be resent along with a temperature change.
 */
export const putSettings = (patch: Record<string, unknown>) =>
  request<SettingsView>("/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  })

export const listSkills = () => request<SettingsView["skills"]>("/skills")

// -------------------------------------------------------------------- sse --

export interface EventStream {
  /** Resolves when the stream ends normally. */
  done: Promise<void>
  close(): void
}

/**
 * Subscribe to a run's events, starting at sequence `afterSeq`.
 *
 * Two things this must get right, both easy to get wrong:
 *
 * 1. **`after` is an inclusive start index, not "the last one I saw".** The
 *    server does `events[after]` first, which is also why the default is `0`
 *    and not `-1`. Passing the last `seq` handled replays that event a second
 *    time; the caller wants `lastSeq + 1`.
 * 2. **Reconnection.** A dropped connection is normal on a local backend that
 *    was restarted, not an error. The caller resubscribes until `done` arrives.
 */
export function streamRun(
  runId: string,
  afterSeq: number,
  onEvent: (event: RunEvent) => void,
): EventStream {
  const controller = new AbortController()

  const done = (async () => {
    const response = await fetch(
      `${BASE}/runs/${runId}/events?after=${afterSeq}`,
      { signal: controller.signal, headers: { Accept: "text/event-stream" } },
    )
    if (!response.ok || !response.body) {
      throw new ApiError(await describe(response), response.status)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    // SSE frames are separated by a blank line, but a chunk boundary can land
    // anywhere, so a partial frame has to survive until the next read.
    let buffer = ""

    try {
      for (;;) {
        const { value, done: finished } = await reader.read()
        if (finished) break
        buffer += decoder.decode(value, { stream: true })

        let split: number
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split)
          buffer = buffer.slice(split + 2)
          const payload = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim())
            .join("")
          if (!payload) continue
          onEvent(JSON.parse(payload) as RunEvent)
        }
      }
    } finally {
      reader.releaseLock()
    }
  })()

  return { done, close: () => controller.abort() }
}