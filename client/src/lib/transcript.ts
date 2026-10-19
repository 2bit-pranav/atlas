/**
 * Fold run events into the parts a turn shows.
 *
 * The same rules as `server/transcript.py`, which builds the stored copy. The
 * live view and the reloaded view must be built identically or a finished
 * answer visibly changes shape when the run ends; change both together.
 *
 * Mutable on purpose: one fold per animation frame over a batch of events, and
 * the store hands React a fresh array afterwards. Copying the whole parts list
 * per token is what made a long answer stutter.
 */

import type { Part, RunEvent, TurnStats } from "@/lib/types"

export interface LiveTurn {
  parts: Part[]
  stats: TurnStats
  callMark: number
  retries: number
}

export const emptyLive = (contextSize = 0): LiveTurn => ({
  parts: [],
  stats: { context_size: contextSize },
  callMark: 0,
  retries: 0,
})

export function fold(live: LiveTurn, event: RunEvent): void {
  const parts = live.parts
  switch (event.type) {
    case "call_start":
      live.callMark = parts.length
      return
    case "model_retry":
      // The discarded attempt already streamed; cut back to where it began.
      parts.length = live.callMark
      live.retries += 1
      return
    case "resumed":
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i]
        if (p.kind === "text") parts[i] = { kind: "superseded", text: p.text }
      }
      return
    case "thinking_delta":
      return append(parts, "reasoning", event.text)
    case "text_delta":
      return append(parts, "text", event.text)
    case "tool_start":
      parts.push({ kind: "tool", id: event.id, name: event.name, args: event.args ?? {},
                   status: "running", text: "" })
      return
    case "tool_args_delta":
      updateTool(parts, event.id, (p) => ({ ...p, args: event.args }))
      return
    case "tool_end":
      updateTool(parts, event.id, (p) => ({
        ...p, status: event.status === "error" ? "error" : "success", text: event.text,
      }))
      return
    case "approval_request":
      parts.push({ kind: "approval", id: event.id, request: event.kind, folder: event.folder ?? null,
                   command: event.command, status: "pending", expires_at: event.expires_at })
      return
    case "approval_result":
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i]
        if (p.kind === "approval" && p.id === event.id) parts[i] = { ...p, status: event.decision }
      }
      return
    case "stats": {
      const { type: _t, seq: _s, ...stats } = event
      live.stats = { ...live.stats, ...stats }
      return
    }
  }
}

function append(parts: Part[], kind: "text" | "reasoning", text: string) {
  if (!text) return
  const last = parts[parts.length - 1]
  if (last && last.kind === kind) {
    parts[parts.length - 1] = { kind, text: last.text + text }
  } else {
    parts.push({ kind, text })
  }
}

function updateTool(parts: Part[], id: string, fn: (p: Extract<Part, { kind: "tool" }>) => Part) {
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]
    if (p.kind === "tool" && p.id === id) parts[i] = fn(p)
  }
}

export const answerText = (parts: Part[]) =>
  parts.filter((p) => p.kind === "text").map((p) => (p as { text: string }).text).join("")
