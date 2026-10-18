/**
 * One function per backend route. No caching, no retries, no state: a retried
 * POST is a duplicated turn, so anything that must survive a dropped
 * connection lives in the store, where it can be seen all at once.
 */

import {
  ApiError,
  type ChatFile,
  type ChatSummary,
  type ChatView,
  type McpServer,
  type RegistryServer,
  type RunEvent,
  type SettingsView,
  type Skill,
  type SkillInstallResult,
  type StartedRun,
} from "@/lib/types"

const BASE = `${(import.meta.env.VITE_ATLAS_API as string | undefined) ?? ""}/api`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: init?.body instanceof FormData
        ? init.headers
        : { "Content-Type": "application/json", ...init?.headers },
    })
  } catch {
    throw new ApiError("Cannot reach the Atlas backend. Is `atlas start` running?", 0)
  }
  if (!response.ok) throw new ApiError(await describe(response), response.status)
  return (await response.json()) as T
}

/** FastAPI's `detail` is the message the backend wrote for a person to read. */
async function describe(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body?.detail === "string") return body.detail
    if (body?.detail) return JSON.stringify(body.detail)
  } catch {
    /* fall through */
  }
  return `${response.status} ${response.statusText}`
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

// ------------------------------------------------------------------ chats --

export const health = () => request<{ status: string }>("/health")
export const listChats = () => request<ChatSummary[]>("/chats")
export const createChat = (title = "") => request<ChatSummary>("/chats", json("POST", { title }))
export const getChat = (id: string) => request<ChatView>(`/chats/${id}`)
export const renameChat = (id: string, title: string) =>
  request<ChatSummary>(`/chats/${id}`, json("PATCH", { title }))
export const deleteChat = (id: string) => request<{ deleted: string }>(`/chats/${id}`, json("DELETE"))
export const exportChat = (id: string) => request<Record<string, unknown>>(`/chats/${id}/export`)
export const importChat = (data: unknown) => request<ChatSummary>("/chats/import", json("POST", data))

export async function uploadFile(chatId: string, file: File): Promise<ChatFile> {
  const form = new FormData()
  form.append("file", file)
  return request<ChatFile>(`/chats/${chatId}/files`, { method: "POST", body: form })
}

export const fileUrl = (chatId: string, name: string) =>
  `${BASE}/chats/${chatId}/files/${encodeURIComponent(name)}`

// ------------------------------------------------------------------ turns --

export const send = (chatId: string, body: { text: string; files: ChatFile[]; thinking: boolean }) =>
  request<StartedRun>(`/chats/${chatId}/messages`, json("POST", body))
export const retry = (turnId: string, thinking: boolean) =>
  request<StartedRun>(`/turns/${turnId}/retry`, json("POST", { thinking }))
export const edit = (turnId: string, body: { text: string; files?: ChatFile[]; thinking: boolean }) =>
  request<StartedRun>(`/turns/${turnId}/edit`, json("POST", body))
export const select = (turnId: string, delta: number) =>
  request<ChatView>(`/turns/${turnId}/select`, json("POST", { delta }))
export const cancel = (runId: string) => request<unknown>(`/runs/${runId}/cancel`, json("POST"))
export const getRun = (runId: string) =>
  request<{ status: string; error: string | null }>(`/runs/${runId}`)

export interface EventStream {
  done: Promise<void>
  close: () => void
}

/**
 * Server-sent events over `fetch`, not `EventSource`: EventSource reconnects
 * on its own with no way to say where to resume, which is how a dropped
 * connection used to replay a sentence.
 */
export function streamRun(runId: string, after: number, onEvent: (e: RunEvent) => void): EventStream {
  const controller = new AbortController()
  const done = (async () => {
    const response = await fetch(`${BASE}/runs/${runId}/events?after=${after}`, {
      signal: controller.signal,
      headers: { Accept: "text/event-stream" },
    })
    if (!response.ok || !response.body) throw new ApiError(await describe(response), response.status)
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
    let buffer = ""
    for (;;) {
      const { value, done: finished } = await reader.read()
      if (finished) return
      buffer += value
      let cut: number
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, cut)
        buffer = buffer.slice(cut + 2)
        for (const line of frame.split("\n")) {
          if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as RunEvent)
        }
      }
    }
  })().catch((error: unknown) => {
    if (controller.signal.aborted) return
    throw error
  })
  return { done, close: () => controller.abort() }
}

// --------------------------------------------------------------- settings --

export const getSettings = () => request<SettingsView>("/settings")
export const putSettings = (patch: Record<string, unknown>) =>
  request<SettingsView>("/settings", json("PUT", patch))

// ----------------------------------------------------------------- skills --

export const listSkills = () => request<Skill[]>("/skills")
export const installSkill = (command: string, choose?: string[], replace = false) =>
  request<SkillInstallResult>("/skills/install", json("POST", { command, choose, replace }))
export async function uploadSkill(file: File): Promise<SkillInstallResult> {
  const form = new FormData()
  form.append("file", file)
  return request<SkillInstallResult>("/skills/upload", { method: "POST", body: form })
}
export const toggleSkill = (folder: string, enabled: boolean) =>
  request<Skill[]>(`/skills/${folder}`, json("PUT", { enabled }))
export const deleteSkill = (folder: string) => request<Skill[]>(`/skills/${folder}`, json("DELETE"))
export const installRequirements = (folder: string) =>
  request<{ ok: boolean; output: string }>(`/skills/${folder}/requirements`, json("POST"))

// -------------------------------------------------------------------- mcp --

export const listMcp = () => request<McpServer[]>("/mcp")
export const upsertMcp = (name: string, config: Record<string, unknown>) =>
  request<McpServer[]>("/mcp", json("POST", { name, config }))
export const deleteMcp = (name: string) => request<McpServer[]>(`/mcp/${name}`, json("DELETE"))
export const toggleMcp = (name: string, enabled: boolean) =>
  request<McpServer[]>(`/mcp/${name}`, json("PUT", { enabled }))
export const reconnectMcp = (name: string) =>
  request<McpServer[]>(`/mcp/${name}/reconnect`, json("POST"))
export const toggleMcpTool = (name: string, tool: string, enabled: boolean) =>
  request<McpServer[]>(`/mcp/${name}/tools/${encodeURIComponent(tool)}`, json("PUT", { enabled }))
export const searchRegistry = (q: string) =>
  request<RegistryServer[]>(`/mcp/registry?q=${encodeURIComponent(q)}`)
