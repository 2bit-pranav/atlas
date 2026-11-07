/**
 * A run's tool calls as steps a person reads: "Read 3 invoices", "Saved
 * invoices.xlsx". Built from each call's name, arguments and result, which the
 * client already has: no model call, so a label costs nothing and is exact.
 *
 * Consecutive calls of one tool are one step. Calls that are Atlas's own
 * plumbing (loading a skill) are `internal`: shown only with Details on.
 */

import type { Part } from "@/api/types"

type ToolPart = Extract<Part, { kind: "tool" }>

export type StepStatus = "done" | "running" | "waiting" | "error"

export interface Step {
  key: string
  label: string
  /** The calls behind it, for Details: `read_pdf invoice-5819.pdf`. */
  detail: string[]
  status: StepStatus
  internal: boolean
  /** What the user answered when it asked: "You said no". */
  note?: string
  /** How long its calls took, when the run recorded it. */
  ms?: number
}

const READS = new Set(["read_text", "read_image", "read_pdf", "read_docx", "read_xlsx", "read"])

const base = (p: unknown) => String(p ?? "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || String(p ?? "")
const short = (s: string, n = 60) => (s.length > n ? s.slice(0, n - 1) + "…" : s)
const arg = (part: ToolPart, key: string): string => {
  const a = part.args
  return a && typeof a === "object" && key in a ? String((a as Record<string, unknown>)[key] ?? "") : ""
}

/** "invoice-5819.pdf", "invoice-5820.pdf" -> "invoices"; mixed names -> "files". */
function noun(names: string[]): string {
  const words = names.map((n) => /^[a-z]+/i.exec(n.replace(/\.[^.]+$/, ""))?.[0]?.toLowerCase() ?? "")
  const first = words[0]
  if (first && first.length > 2 && words.every((w) => w === first)) return first.endsWith("s") ? first : `${first}s`
  return "files"
}

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return short(url, 40)
  }
}

/** The label for a run of calls to one tool. */
function label(name: string, calls: ToolPart[]): string {
  const n = calls.length
  const first = calls[0]
  const failed = calls.every((c) => c.status === "error")
  if (READS.has(name)) {
    const names = calls.map((c) => base(arg(c, "path")))
    return n === 1 ? `Read ${names[0] || "a file"}` : `Read ${n} ${noun(names)}`
  }
  switch (name) {
    case "find_files": {
      const found = /^(\d+) files?/.exec(first.text)?.[1]
      const q = arg(first, "query")
      return `Searched your folders${q ? ` for "${short(q, 40)}"` : ""}` +
             (first.status === "success" ? (found ? ` · ${found} found` : /^No file/.test(first.text) ? " · nothing found" : "") : "")
    }
    case "list_folder": return `Looked in ${base(arg(first, "path")) || "your folders"}`
    case "web_search": return n === 1 ? `Searched the web for "${short(arg(first, "query"), 50)}"` : `Searched the web ${n} times`
    case "read_url": return n === 1 ? `Read ${host(arg(first, "url"))}` : `Read ${n} web pages`
    case "create_document":
    case "write":
      return failed ? `Could not save ${base(arg(first, "path"))}`
        : n === 1 ? `Saved ${base(arg(first, "path"))}` : `Saved ${n} files`
    case "edit_docx":
    case "set_cell":
    case "edit":
      return failed ? `Did not change ${base(arg(first, "path"))}` : n === 1 ? `Changed ${base(arg(first, "path"))}` : `Made ${n} changes`
    case "copy_file": return failed ? `Did not copy ${base(arg(first, "path"))}` : n === 1 ? `Copied ${base(arg(first, "path"))}` : `Copied ${n} files`
    case "move_file": return failed ? `Did not move ${base(arg(first, "path"))}` : n === 1 ? `Moved ${base(arg(first, "path"))}` : `Moved ${n} files`
    case "delete_file": return failed ? `Did not delete ${base(arg(first, "path"))}` : n === 1 ? `Deleted ${base(arg(first, "path"))}` : `Deleted ${n} files`
    case "calculate":
    case "dates": {
      const expr = arg(first, "expression") || arg(first, "expr")
      const result = first.status === "success" && first.text.length < 40 ? ` = ${first.text.trim()}` : ""
      return n === 1 && expr ? `Worked out ${short(expr, 50)}${result}` : "Did the maths"
    }
    case "shell": {
      const skill = /ATLAS_SKILLS\}?\/([\w-]+)\//.exec(arg(first, "command"))?.[1]
      if (failed) return skill ? `The ${skill} tool did not run` : "A command did not run"
      return skill ? `Ran the ${skill} tool` : n === 1 ? "Ran a command" : `Ran ${n} commands`
    }
    case "skills": return `Loaded the ${arg(first, "skill_name") || "a"} skill`
    case "page_read":
    case "page_find":
      return "Read the page"
    default:
      return `Used ${name.replace(/_/g, " ")}`
  }
}

function detail(call: ToolPart): string {
  const a = call.args && typeof call.args === "object" ? (call.args as Record<string, unknown>) : {}
  const main = a.path ?? a.query ?? a.url ?? a.command ?? a.expression ?? a.skill_name ?? ""
  return `${call.name} ${short(typeof main === "string" ? (READS.has(call.name) ? base(main) : main) : JSON.stringify(main), 80)}`.trim()
}

export function toSteps(parts: Part[], running: boolean): Step[] {
  const steps: Step[] = []
  let run: ToolPart[] = []
  const flush = () => {
    if (!run.length) return
    const name = run[0].name
    const status: StepStatus = run.some((c) => c.status === "running") ? "running"
      : run.every((c) => c.status === "error") ? "error" : "done"
    const ms = run.every((c) => c.ms !== undefined) ? run.reduce((t, c) => t + (c.ms ?? 0), 0) : undefined
    steps.push({ key: run[0].id || `${name}-${steps.length}`, label: label(name, run), detail: run.map(detail),
                 status, internal: name === "skills", ms })
    run = []
  }
  for (const part of parts) {
    if (part.kind === "approval") {
      // It is about the call just made: say what the user answered on that step.
      flush()
      const step = steps[steps.length - 1]
      const note = { denied: "You said no", expired: "No answer in time", allowed_chat: "Allowed for this task" }[part.status as string]
      if (step && note) step.note = note
      continue
    }
    if (part.kind !== "tool") {
      // Text or reasoning between calls ends a run: two separate searches stay two steps.
      if (part.kind === "text") flush()
      continue
    }
    if (run.length && run[0].name !== part.name) flush()
    run.push(part)
  }
  flush()
  // A pending approval holds the call it is about: that step waits for the user.
  if (running && parts.some((p) => p.kind === "approval" && p.status === "pending")) {
    const last = [...steps].reverse().find((s) => s.status === "running") ?? steps[steps.length - 1]
    if (last) last.status = "waiting"
  }
  const last = parts[parts.length - 1]
  if (running && last?.kind === "text") steps.push({ key: "answer", label: "Writing the answer", detail: [], status: "running", internal: false })
  return steps
}

/** Web pages a run used, from web_search results and read_url calls, once each. */
export function sources(parts: Part[]): { url: string; title: string; site: string }[] {
  const out = new Map<string, { url: string; title: string; site: string }>()
  for (const p of parts) {
    if (p.kind !== "tool" || p.status !== "success") continue
    if (p.name === "web_search") {
      for (const m of p.text.matchAll(/^\[\d+\] (.+?) - ([^\s]+) \(.*\)\n\s+(https?:\/\/\S+)/gm))
        if (!out.has(m[3])) out.set(m[3], { url: m[3], title: m[1], site: m[2] })
    }
    if (p.name === "read_url") {
      const url = arg(p, "url")
      if (url && !out.has(url)) out.set(url, { url, title: p.text.split("\n")[0].split(" - ")[0], site: host(url) })
    }
  }
  return [...out.values()]
}

/** Files a read tool downloaded from a link (read_pdf on an https URL): inputs, not made.
 * A file read and then edited is something the task made, and keeps its card. */
export function downloaded(parts: Part[]): Set<string> {
  return new Set(parts.filter((p): p is ToolPart => p.kind === "tool" && READS.has(p.name) && /^https?:\/\//i.test(arg(p, "path")))
                      .map((p) => base(arg(p, "path").split("?")[0])))
}

export { noun }
