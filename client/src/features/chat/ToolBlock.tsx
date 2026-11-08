/**
 * Tool calls, compact. One call is one line: status, name, what it acted on;
 * a click shows its arguments and output. Calls in a row fold into a single
 * summary line ("3 tool calls · read_pdf, read_docx · 1 failed") that opens to
 * those lines, so a long run of calls takes one line of the answer, not a box
 * each. Shell results arrive as JSON (`{output, error, exit_code}`) and are
 * shown as the text they contain.
 */

import { memo, useState } from "react"
import { CheckCircle2, ChevronRight, Loader2, XCircle } from "lucide-react"

import type { Part } from "@/api/types"
import { cn } from "@/lib/cn"

export type ToolPart = Extract<Part, { kind: "tool" }>

function StatusIcon({ status }: { status: ToolPart["status"] }) {
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
  if (status === "error") return <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
  return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
}

/** A run of tool calls: one call as its own line, several folded under a summary line. */
export const ToolGroup = memo(function ToolGroup({ parts, defaultOpen }: { parts: ToolPart[]; defaultOpen: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null)
  if (parts.length === 1) return <div className="my-1.5"><ToolLine part={parts[0]} defaultOpen={defaultOpen} /></div>
  const isOpen = open ?? defaultOpen
  const running = parts.some((p) => p.status === "running")
  const failed = parts.filter((p) => p.status === "error").length
  const names = [...new Set(parts.map((p) => p.name))]
  return (
    <div className="my-1.5">
      <button type="button" onClick={() => setOpen(!isOpen)} aria-expanded={isOpen}
              className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-muted/50">
        <StatusIcon status={running ? "running" : failed ? "error" : "success"} />
        <span className={cn("shrink-0 text-xs font-medium text-foreground/80", running && "shimmer-text")}>
          {parts.length} tool calls
        </span>
        <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
          {names.join(", ")}{failed > 0 && <span className="text-destructive"> · {failed} failed</span>}
        </span>
        <ChevronRight className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />
      </button>
      {isOpen && (
        <div className="ml-3 border-l pl-2">
          {parts.map((p, i) => <ToolLine key={p.id || i} part={p} defaultOpen={false} />)}
        </div>
      )}
    </div>
  )
})

/** One tool call as a line; its arguments and output when opened. */
const ToolLine = memo(function ToolLine({ part, defaultOpen }: { part: ToolPart; defaultOpen: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null)
  const isOpen = open ?? defaultOpen
  const args = part.args as Record<string, unknown> | null
  const summary = args && typeof args === "object"
    ? String(args.command ?? args.path ?? args.skill_name ?? args.search ?? Object.values(args)[0] ?? "")
    : ""
  const { body, note } = readable(part.text)

  return (
    <div>
      <button type="button" onClick={() => setOpen(!isOpen)} aria-expanded={isOpen}
              className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-muted/50">
        <StatusIcon status={part.status} />
        <span className={cn("shrink-0 font-mono text-xs font-medium text-foreground/80", part.status === "running" && "shimmer-text")}>
          {part.name}
        </span>
        <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{summary}</span>
        <ChevronRight className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />
      </button>
      {isOpen && (
        <div className="mb-2 ml-3 space-y-2 border-l pl-3 pt-1">
          <Section title="Arguments">{JSON.stringify(part.args, null, 2)}</Section>
          {part.status !== "running" && <Section title={part.status === "error" ? "Error" : "Output"}>{body || "(no output)"}</Section>}
          {note && <p className="text-[11px] italic text-muted-foreground">{note}</p>}
        </div>
      )}
    </div>
  )
})

function Section({ title, children }: { title: string; children: string }) {
  return (
    <div>
      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground/70">{title}</p>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-code p-2.5 font-mono text-xs text-code-foreground">
        {children}
      </pre>
    </div>
  )
}

/** Shell JSON to text, and Atlas's own recovery notes split out of the output. */
function readable(text: string): { body: string; note: string } {
  const lines = text.split("\n")
  const notes = lines.filter((l) => l.startsWith("[Atlas]"))
  let body = lines.filter((l) => !l.startsWith("[Atlas]")).join("\n").trim()
  try {
    const parsed = JSON.parse(body) as { output?: string; error?: string; exit_code?: number }
    if (parsed && typeof parsed === "object" && ("exit_code" in parsed || "output" in parsed)) {
      body = [parsed.output?.trim(), parsed.error?.trim(), parsed.exit_code ? `exit code ${parsed.exit_code}` : ""]
        .filter(Boolean).join("\n")
    }
  } catch {
    /* plain text already */
  }
  return { body, note: notes.join(" ").replace(/\[Atlas\]\s*/g, "") }
}
