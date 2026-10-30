import { useEffect, useState } from "react"
import { ShieldAlert } from "lucide-react"
import { atlas } from "@/state/store"
import type { Part } from "@/api/types"
import { cn } from "@/lib/cn"

const ASK_TITLE = {
  install: "Atlas wants to install something",
  access: "Atlas wants to use a folder outside its allowed ones",
  tool: "Atlas wants to use a tool that needs your approval",
  page: "Atlas read a web page and now wants to run this",
} as const
const DONE_TITLE = { install: "Install request", access: "Folder access request", tool: "Tool approval",
                     page: "After reading a web page" } as const

/**
 * The agent wants to do something that needs the user: install a package,
 * reach a folder outside the allowed ones, or call an MCP tool marked "ask".
 * Allow or Deny; no answer by the deadline counts as Deny (the backend
 * decides, this only shows the clock).
 */
export function ApprovalCard({ part, live }: { part: Extract<Part, { kind: "approval" }>; live: boolean }) {
  const [now, setNow] = useState(() => Date.now())
  const [sent, setSent] = useState(false)
  const pending = part.status === "pending" && live
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [pending])
  const left = Math.max(0, Math.ceil((part.expires_at - now) / 1000))
  const outcome = {
    pending: live ? null : "Not answered",
    allowed: "Allowed",
    denied: "Declined: not run",
    expired: "No answer in time: not run",
  }[part.status]
  return (
    <div className={cn("my-3 rounded-xl border p-3.5",
                       pending ? "border-amber-500/50 bg-amber-500/5" : "bg-muted/30")}>
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShieldAlert className={cn("h-4 w-4", pending ? "text-amber-500" : "text-muted-foreground")} />
        {(pending ? ASK_TITLE : DONE_TITLE)[part.request ?? "install"]}
        {pending && <span className="ml-auto font-mono text-xs text-muted-foreground">{left}s</span>}
        {outcome && (
          <span className={cn("ml-auto text-xs", part.status === "allowed" ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
            {outcome}
          </span>
        )}
      </div>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-code p-2.5 font-mono text-xs text-code-foreground">{part.command}</pre>
      {pending && (
        <div className="mt-3 flex items-center gap-2">
          <button type="button" disabled={sent} onClick={() => { setSent(true); void atlas.answerApproval(part.id, true) }}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50">
            Allow
          </button>
          <button type="button" disabled={sent} onClick={() => { setSent(true); void atlas.answerApproval(part.id, false) }}
                  className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50">
            Deny
          </button>
          <span className="text-[11px] text-muted-foreground">
            {part.request === "access" && part.folder
              ? <>Allows {part.access === "write" ? "changing" : "reading"} {part.folder} for the rest of this
                  answer. To allow it always, add it under Settings &gt; Access.</>
              : "Runs on this computer with your permissions."}
          </span>
        </div>
      )}
    </div>
  )
}
