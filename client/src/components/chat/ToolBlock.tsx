/**
 * One tool call, collapsible: the tool's name and status in a row, and its
 * arguments and output when opened. Shell results arrive as JSON
 * (`{output, error, exit_code}`) and are shown as the text they contain.
 */

import { memo, useState } from "react"
import { CheckCircle2, ChevronDown, Loader2, Wrench, XCircle } from "lucide-react"

import type { Part } from "@/lib/types"
import { cn } from "@/lib/utils"

type ToolPart = Extract<Part, { kind: "tool" }>

export const ToolBlock = memo(function ToolBlock({ part, defaultOpen }: { part: ToolPart; defaultOpen: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null)
  const isOpen = open ?? defaultOpen
  const args = part.args as Record<string, unknown> | null
  const summary = args && typeof args === "object"
    ? String(args.command ?? args.path ?? args.skill_name ?? args.url ?? Object.values(args)[0] ?? "")
    : ""
  const { body, note } = readable(part.text)

  return (
    <div className="my-2 rounded-lg border bg-muted/30">
      <button type="button" onClick={() => setOpen(!isOpen)}
              className="group flex w-full items-center gap-2 px-3 py-2 text-left">
        {part.status === "running" ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
          : part.status === "error" ? <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
          : <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />}
        <Wrench className="h-3 w-3 shrink-0 text-muted-foreground/60" />
        <span className={cn("shrink-0 font-mono text-xs font-medium", part.status === "running" && "shimmer-text")}>{part.name}</span>
        <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">{summary}</span>
        <ChevronDown className={cn("ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-180")} />
      </button>
      {isOpen && (
        <div className="space-y-2 border-t px-3 py-2.5">
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
