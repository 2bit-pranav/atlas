/**
 * One tool call, as the backend reported it.
 *
 * There was a demo version of this that showed invented "Planning analysis
 * approach" steps with no relation to anything the agent did. This one shows
 * the actual `shell` / `skills` / `read` call, the arguments it was given, and
 * the output it produced -- which is the only thing that makes a 2B model's
 * tool use debuggable when it gets something wrong.
 *
 * Arguments and output are both collapsed by default because a DuckDB traceback
 * is 40 lines and the interesting field is whether the call succeeded.
 */

import React from "react"
import {
  CheckCircle2,
  ChevronRight,
  Loader2,
  Terminal,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"

export interface ToolCardProps {
  name: string
  /** Raw tool arguments, whatever shape the model produced. */
  args: unknown
  status: "running" | "success" | "error"
  /** Tool result text. Empty while running. */
  text: string
}

export const ToolCard: React.FC<ToolCardProps> = ({
  name,
  args,
  status,
  text,
}) => {
  const [open, setOpen] = React.useState(false)
  const argText = React.useMemo(() => stringify(args), [args])

  return (
    <div className="mb-2 rounded-xl border border-border/60 bg-muted/20">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] hover:bg-muted/40 transition-colors"
      >
        <ChevronRight
          className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-90")}
        />
        <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-mono font-medium">{name}</span>

        {status === "running" ? (
          <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-muted-foreground" />
        ) : status === "error" ? (
          <XCircle className="ml-auto h-3.5 w-3.5 text-destructive" />
        ) : (
          <CheckCircle2 className="ml-auto h-3.5 w-3.5 text-emerald-500" />
        )}
      </button>

      {open && (
        <div className="space-y-1.5 border-t border-border/60 px-3 py-2">
          {argText && argText !== "{}" && (
            <section>
              <p className="mb-0.5 text-[10px] uppercase tracking-wide text-muted-foreground/80">
                arguments
              </p>
              <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
                {argText}
              </pre>
            </section>
          )}
          {text && (
            <section>
              <p className="mb-0.5 text-[10px] uppercase tracking-wide text-muted-foreground/80">
                output
              </p>
              <pre
                className={cn(
                  "max-h-72 overflow-y-auto whitespace-pre-wrap font-mono text-[11px]",
                  status === "error" ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {text}
              </pre>
            </section>
          )}
          {!argText && !text && (
            <p className="text-[11px] text-muted-foreground">No output.</p>
          )}
        </div>
      )}
    </div>
  )
}

/** Pretty-print, but never throw: a malformed arg should not blank the card. */
function stringify(value: unknown): string {
  if (value === null || value === undefined) return ""
  if (typeof value === "string") return value
  try {
    return JSON.stringify(value, null, 2) ?? ""
  } catch {
    return String(value)
  }
}