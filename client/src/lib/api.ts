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
  type ModelList,
  type RegistryServer,
  type RestartStatus,
  type RunEvent,
  type SettingsView,
  type WorkspaceFile,
  type Skill,
  type SkillInstallResult,
  type StartedRun,
} from "@/lib/types"

/**
 * Where the backend is, and the pairing token. The web UI is served by the
 * backend (or proxied by Vite), so it needs neither. The browser extension
 * sets both with `configureApi`.
 */
let BASE = `${(import.meta.env.VITE_ATLAS_API as string | undefined) ?? ""}/api`
let TOKEN = ""

export function configureApi({ base, token }: { base?: string; token?: string }) {
  if (base !== undefined) BASE = `${base.replace(/\/$/, "")}/api`
  if (token !== undefined) TOKEN = token
}

const auth = (): Record<string, string> => (TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {})

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: init?.body instanceof FormData
        ? { ...auth(), ...init.headers }
        : { "Content-Type": "application/json", ...auth(), ...init?.headers },
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

export const listChats = () => request<ChatSummary[]>("/chats")
export const createChat = (title = "", page?: { source: "extension"; page_url: string; page_title: string }) =>
  request<ChatSummary>("/chats", json("POST", { title, ...page }))
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

/** A workspace file. `name` may contain folders; each segment is encoded. A URL
 * carries no header, so the extension's token goes in the query. */
export function fileUrl(chatId: string, name: string, download = false): string {
  const query = new URLSearchParams()
  if (download) query.set("download", "1")
  if (TOKEN) query.set("token", TOKEN)
  const qs = query.toString()
  return `${BASE}/chats/${chatId}/files/${name.split("/").map(encodeURIComponent).join("/")}${qs ? `?${qs}` : ""}`
}
/** A PDF by its link (`file://` or web) copied into the chat's workspace by the backend. */
export const importFile = (chatId: string, url: string) =>
  request<ChatFile>(`/chats/${chatId}/files/import`, json("POST", { url }))
export const deleteUpload = (chatId: string, name: string) =>
  request<unknown>(`/chats/${chatId}/files/${name.split("/").map(encodeURIComponent).join("/")}`, json("DELETE"))
export const listWorkspace = (chatId: string) => request<WorkspaceFile[]>(`/chats/${chatId}/workspace`)

// ------------------------------------------------------------------ turns --

/** The tab a side-panel message is about; it turns on the page tools. */
export interface PageRef {
  url: string
  title: string
}

export const send = (chatId: string, body: { text: string; files: ChatFile[]; thinking: boolean; page?: PageRef | null }) =>
  request<StartedRun>(`/chats/${chatId}/messages`, json("POST", body))
export const retry = (turnId: string, thinking: boolean, page?: PageRef | null) =>
  request<StartedRun>(`/turns/${turnId}/retry`, json("POST", { thinking, page }))
export const edit = (turnId: string, body: { text: string; files?: ChatFile[]; thinking: boolean; page?: PageRef | null }) =>
  request<StartedRun>(`/turns/${turnId}/edit`, json("POST", body))
/** The client's result for a `client_call` event (a page operation). */
export const answerCall = (runId: string, callId: string, result: Record<string, unknown>) =>
  request<unknown>(`/runs/${runId}/calls/${callId}`, json("POST", result))
export const select = (turnId: string, delta: number) =>
  request<ChatView>(`/turns/${turnId}/select`, json("POST", { delta }))
export const answerApproval = (runId: string, approvalId: string, allow: boolean) =>
  request<unknown>(`/runs/${runId}/approvals/${approvalId}`, json("POST", { allow }))
export const cancel = (runId: string) => request<unknown>(`/runs/${runId}/cancel`, json("POST"))
export const getRun = (runId: string) =>
  request<{ status: string; error: string | null }>(`/runs/${runId}`)

export interface EventStream {
  done: Promise<void>
  close: () => void
}

/**
 * Server-sent events over `fetch`, not `EventSource`: EventSource reconnects
 * on its own with no way to say where to resume, so a dropped connection
 * would replay text already shown.
 */
export function streamRun(runId: string, after: number, onEvent: (e: RunEvent) => void): EventStream {
  const controller = new AbortController()
  const done = (async () => {
    const response = await fetch(`${BASE}/runs/${runId}/events?after=${after}`, {
      signal: controller.signal,
      headers: { Accept: "text/event-stream", ...auth() },
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
export const getPairing = () => request<{ token: string; base: string }>("/pairing")
/** The user's details for fill suggestions (web UI only). */
export const getProfile = () => request<{ text: string }>("/profile")
export const putProfile = (text: string) => request<{ text: string }>("/profile", json("PUT", { text }))
/** Suggested values for a form's fields; `missing` lists the labels the details do not answer. */
export const suggestFill = (fields: { id: string; label: string }[], title: string) =>
  request<{ values: Record<string, string>; missing: string[] }>("/extension/fill", json("POST", { fields, title }))
export const resetPairing = () => request<{ token: string }>("/pairing/reset", json("POST"))
/** A web page's table saved as xlsx/csv by the backend; no model involved. */
export const saveTable = (body: { rows: string[][]; title: string; url: string; format: "xlsx" | "csv"; folder?: string }) =>
  request<{ path: string; rows: number }>("/extension/table", json("POST", body))
export const listModels = () => request<ModelList>("/models")
export const restartStatus = () => request<RestartStatus>("/restart")
export const restart = () => request<{ ok: boolean }>("/restart", json("POST"))
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
export const setMcpToolMode = (name: string, tool: string, mode: "on" | "ask" | "off") =>
  request<McpServer[]>(`/mcp/${name}/tools/${encodeURIComponent(tool)}`, json("PUT", { mode }))
export const searchRegistry = (q: string) =>
  request<RegistryServer[]>(`/mcp/registry?q=${encodeURIComponent(q)}`)
