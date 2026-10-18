/**
 * The Atlas backend contract, transcribed from the code that serves it.
 *
 * This file is the only place the frontend is allowed to know what the API
 * looks like. Everything else imports from here, so a backend change breaks in
 * one file rather than seven.
 *
 * Source of truth:
 *   routes     agent/server/app.py
 *   events     agent/server/events.py
 *   sequence   agent/server/runs.py
 *
 * Nothing in this file is invented. There is no `previewData`, no
 * `thinkingSteps`, and no `LocalModel[]` -- those were shapes from a demo
 * engine that no longer exists, and every one of them was a lie about what the
 * backend would actually send.
 */

// ------------------------------------------------------------------ tiers --

/** Which settings need the backend restarted before they take effect. */
export type Tier = "live" | "restart"

// ---------------------------------------------------------------- settings --

/**
 * `GET /settings` and `PUT /settings` both return this.
 *
 * `values` is flat and dotted: `{"sampling.temperature": 0.7}`, not nested.
 * That is deliberate -- the dotted key is also the tier key and the thing a
 * `PUT` names, so one string identifies a setting in all three places.
 */
export interface SettingsView {
  values: Record<string, unknown>
  tiers: Record<string, Tier>
  /** RESTART keys whose file value differs from what the servers launched with. */
  pending_restart: Record<string, unknown>
  tools: ToolDescription
  memory: MemoryDescription
  skills: SkillSummary[]
}

export interface ToolDescription {
  groups: Record<string, boolean>
  builtin_tools: string[]
  interventions: boolean
}

export interface MemoryDescription {
  enabled: boolean
  /**
   * Why memory is off. Shown in the UI verbatim and not editable: the backend
   * refuses `memory.enabled: true`, and the reason it gives is the entire basis
   * on which branch isolation currently holds. Hiding that would make a
   * deliberate safety choice look like a missing feature.
   */
  reason: string
}

export interface SkillSummary {
  name: string
  description: string
  /** Directory name under the skills root. */
  folder: string
  path: string
  scripts: string[]
}

// ------------------------------------------------------------------ chats --

export type TurnStatus =
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"

/** One node on the currently selected path of the chat tree. */
export interface TurnView {
  id: string
  user_text: string
  files: ChatFile[]
  status: TurnStatus
  /**
   * Milliseconds since the epoch, already in JS's units. Verified against a
   * live run: the backend stores `time.time() * 1000`, so this needs no
   * conversion -- multiplying by 1000 again would put every message in the
   * year 58000.
   */
  created_at: number
  snapshot: string | null
  /** Index among this turn's versions, for the `<` / `>` control. */
  version: number
  version_count: number
}

export interface ChatFile {
  name: string
  type: string
  path: string
  size: number
}

export interface ChatView {
  id: string
  title: string
  turns: TurnView[]
  active_run: string | null
}

export interface ChatListItem {
  id: string
  title: string
  created_at: number
  updated_at: number
}

/** One readable message as `GET /chats/{id}/turns/{turn_id}` returns it. */
export interface StoredMessage {
  role: string
  kind: "text" | "tool_use" | "tool_result"
  text?: string
  name?: string | null
  input?: Record<string, unknown>
  status?: string
}

// ------------------------------------------------------------------- runs --

export interface RunRef {
  run_id: string
  turn_id: string
}

export interface RunView {
  id: string
  chat_id: string
  turn_id: string
  status: string
  error: string | null
  events: number
}

/**
 * Everything `GET /runs/{id}/events` can send.
 *
 * `seq` is assigned server-side. The `after` query parameter is an **inclusive
 * start index**, so resuming after the last event handled means sending
 * `after=<seq + 1>` -- sending `after=<seq>` replays it. The client also drops
 * anything it has already seen, so a mistake here costs one wasted frame
 * rather than a duplicated sentence.
 *
 * `done` and `error` are mutually exclusive and always last.
 */
export type RunEvent =
  | { seq: number; type: "run_started"; chat_id: string; turn_id: string }
  | { seq: number; type: "thinking_delta"; text: string }
  | { seq: number; type: "text_delta"; text: string }
  | { seq: number; type: "tool_start"; id: string; name: string; args: unknown }
  | {
      seq: number
      type: "tool_args_delta"
      id: string
      name?: string | null
      args: unknown
    }
  | {
      seq: number
      type: "tool_end"
      id: string
      name: string
      status: string
      text: string
    }
  | {
      seq: number
      type: "usage"
      input: number
      output: number
      total: number
      /** Present only when the model reported nothing at all. */
      reported?: number
    }
  | { seq: number; type: "done"; status: string; message?: string | null }
  | { seq: number; type: "error"; status: string; message: string | null }

/** `error` details, so the UI can tell a backend 409 from a dead connection. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ApiError"
  }
}