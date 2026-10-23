/**
 * The API contract, transcribed from `server/app.py` and `server/extensions.py`.
 *
 * One file, so a backend change breaks in one place. Two footguns worth
 * remembering: `created_at` is already epoch *milliseconds*, and `?after=` on
 * the event stream is the first sequence number the client has NOT seen.
 */

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export type TurnStatus = "running" | "completed" | "failed" | "cancelled" | "interrupted"

export interface ChatFile {
  name: string
  path: string
  size: number
  type: string
}

export interface ChatSummary {
  id: string
  title: string
  created_at: number
  updated_at: number
  /** `extension`: started in the browser side panel, about `page_url`. */
  source?: "web" | "extension"
  page_url?: string
  page_title?: string
}

export type Part =
  | { kind: "text"; text: string }
  | { kind: "reasoning"; text: string }
  /** An answer the model gave before it was sent back to work after a failure. */
  | { kind: "superseded"; text: string }
  | {
      kind: "tool"
      id: string
      name: string
      args: unknown
      status: "running" | "success" | "error"
      text: string
    }
  | {
      /** The agent is waiting for the user to allow or deny something. */
      kind: "approval"
      id: string
      /** What is asked: an install, a folder outside the allowed ones, or an MCP tool marked "ask". */
      request?: "install" | "access" | "tool" | "page"
      folder?: string | null
      command: string
      status: "pending" | "allowed" | "denied" | "expired"
      expires_at: number
    }

/** A passage attached to a question (from the former preview panel; kept so older chats show it). */
export interface Ref {
  file: string
  path: string | null
  quote: string
}

/** A file the run created or changed, for the download chips. */
export interface ChangedFile {
  name: string
  size: number
  change: "created" | "modified"
}

export interface WorkspaceFile {
  name: string
  size: number
  modified: number
  type: string
}

export interface TurnStats {
  model?: string
  files?: ChangedFile[]
  context_size?: number
  context_used?: number
  prompt_tokens?: number
  completion_tokens?: number
  tokens_per_second?: number
  prompt_per_second?: number
  model_calls?: number
  duration_ms?: number
}

export interface Turn {
  id: string
  parent_id: string | null
  user_text: string
  files: ChatFile[]
  refs: Ref[]
  status: TurnStatus
  created_at: number
  render: Part[]
  stats: TurnStats | null
  error: string | null
  version: number
  versions: string[]
}

export interface RunRef {
  id: string
  chat_id: string
  turn_id: string
  status: string
}

export interface ChatView extends ChatSummary {
  turns: Turn[]
  active_run: RunRef | null
}

export interface StartedRun {
  run: RunRef
  chat: ChatView
}

export type RunEvent = { seq: number } & (
  | { type: "run_started"; chat_id: string; turn_id: string }
  | { type: "call_start" }
  | { type: "model_retry"; reason: string; attempt: number; of: number }
  | { type: "resumed"; reason: string }
  | { type: "thinking_delta"; text: string }
  | { type: "text_delta"; text: string }
  | { type: "tool_start"; id: string; name: string; args: unknown }
  | { type: "tool_args_delta"; id: string; name: string | null; args: unknown }
  | { type: "tool_end"; id: string; name: string; status: string; text: string }
  | { type: "approval_request"; id: string; kind: "install" | "access" | "tool" | "page"; command: string; folder?: string;
      timeout: number; expires_at: number }
  | { type: "approval_result"; id: string; decision: "allowed" | "denied" | "expired" }
  /** The backend asks the client to do something (the extension: a page operation). */
  | { type: "client_call"; id: string; op: string; args: Record<string, unknown> }
  | ({ type: "stats" } & TurnStats)
  | { type: "usage"; input: number; output: number; total: number; reported?: number }
  | { type: "done"; status: TurnStatus }
  | { type: "error"; status: TurnStatus; message: string | null }
)

// --------------------------------------------------------------- settings --

export type Tier = "live" | "restart"

/** Something a skill needs installed, and whether it is. */
export interface Requirement {
  manager: "pip" | "npm"
  package: string
  /** env: Atlas's Python; global: npm -g; skill: the skill's own node_modules. */
  scope: "env" | "global" | "skill"
  installed: boolean
}

export interface Skill {
  name: string
  description: string
  error: string | null
  folder: string
  path: string
  enabled: boolean
  scripts: string[]
  requirements: Requirement[]
  bytes: number
  tokens: number
  bundled: boolean
  origin: { type: string; source?: string; command?: string; installed_at?: number } | null
}

export type ToolMode = "on" | "ask" | "off"

export interface McpTool {
  name: string
  agent_name: string
  description: string
  enabled: boolean
  /** "ask": the user approves each call. */
  mode: ToolMode
  tokens: number
}

export interface McpServer {
  name: string
  config: Record<string, unknown>
  transport: "local" | "remote"
  status: "connected" | "connecting" | "failed" | "stopped" | "disabled"
  error: string | null
  enabled: boolean
  /** Its arguments hold {atlas:folders}, filled with the allowed folders. */
  uses_folders: boolean
  tools: McpTool[]
  tokens: number
}

export interface RegistryOption {
  kind: string
  local: boolean
  config: Record<string, unknown>
  env: { name: string; description?: string; isRequired?: boolean; isSecret?: boolean }[]
}

export interface RegistryServer {
  name: string
  title: string
  description: string
  version: string | null
  repository: string | null
  options: RegistryOption[]
}

/** A model in the models folder (one subfolder each). */
export interface LocalModel {
  name: string
  file: string
  mmproj: string | null
  bytes: number
}

export interface ModelList {
  models: LocalModel[]
  /** The model llama-server was started with. */
  loaded: string
  /** The model in settings.json; differs from `loaded` until a restart. */
  selected: string
}

/** How the last restart ("Restart now" in Settings) went. */
export interface RestartStatus {
  /** False when Atlas was not started by `atlas start` and cannot restart itself. */
  available: boolean
  state?: "restarting" | "ready" | "failed"
  at?: number
  model?: string
  error?: string | null
}

export interface SettingsView {
  values: Record<string, unknown>
  tiers: Record<string, Tier>
  pending_restart: Record<string, unknown>
  tools: { available: string[]; builtin_tools: string[]; atlas_tools: string[]; interventions: boolean }
  skills: Skill[]
  mcp: McpServer[]
  paths: { root: string; data: string }
  /** What the loaded model takes in, from llama-server's /props. */
  modalities: { vision?: boolean; audio?: boolean }
}

export interface SkillInstallResult {
  installed: { name: string; folder: string }[]
  choices: { name: string; folder: string; description: string }[]
  skills: Skill[]
}
