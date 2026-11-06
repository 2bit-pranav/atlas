import { useEffect, useState } from "react"
import { ShieldAlert } from "lucide-react"
import { atlas } from "@/state/store"
import { usePrefs } from "@/state/prefs"
import type { Part } from "@/api/types"
import { cn } from "@/lib/cn"
import { question } from "@/features/chat/approvalText"

type ApprovalPart = Extract<Part, { kind: "approval" }>

/**
 * The agent wants to do something that needs the user: save or change a file
 * in their folders, delete one, run a command, install, or use a tool set to
 * Ask. No answer by the deadline counts as No (the backend decides; this only
 * shows the clock). "Allow for this task" covers the rest of the chat.
 */
export function ApprovalCard({ part, live }: { part: ApprovalPart; live: boolean }) {
  const prefs = usePrefs()
  const [now, setNow] = useState(() => Date.now())
  const [sent, setSent] = useState(false)
  const pending = part.status === "pending" && live
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [pending])
  const left = Math.max(0, Math.ceil((part.expires_at - now) / 1000))
  const { title, showCommand } = question(part)
  const outcome = {
    pending: live ? null : "Not answered",
    allowed: "Allowed",
    allowed_chat: "Allowed for this task",
    denied: "Declined",
    expired: "No answer in time",
  }[part.status]
  const answer = (allow: boolean, scope?: "chat") => {
    setSent(true)
    void atlas.answerApproval(part.id, allow, scope)
  }
  return (
    <div className={cn("my-3 rounded-xl border p-3 first:mt-0 last:mb-0",
                       pending ? "border-ask bg-ask/10" : "bg-muted/30")}>
      <div className="flex items-start gap-2 text-[13px] font-semibold">
        <ShieldAlert className={cn("mt-0.5 h-4 w-4 shrink-0", pending ? "text-ask" : "text-muted-foreground")} />
        <span className="font-display">{title}</span>
        {pending && prefs.taskDetails && <span className="ml-auto font-mono text-xs text-muted-foreground">{left}s</span>}
        {outcome && (
          <span className={cn("ml-auto shrink-0 text-xs", part.status.startsWith("allowed") ? "text-ok" : "text-muted-foreground")}>
            {outcome}
          </span>
        )}
      </div>
      {(showCommand || prefs.taskDetails) && (
        <pre className="mt-2.5 overflow-x-auto whitespace-pre-wrap break-all rounded-lg border bg-card px-2.5 py-2 font-mono text-xs">{part.command}</pre>
      )}
      {pending && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button type="button" disabled={sent} onClick={() => answer(true)}
                  className="rounded-lg border border-primary bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50">
            Allow
          </button>
          {part.chat && (
            <button type="button" disabled={sent} onClick={() => answer(true, "chat")}
                    className="rounded-lg border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50">
              Allow for this task
            </button>
          )}
          <button type="button" disabled={sent} onClick={() => answer(false)}
                  className="rounded-lg border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50">
            No
          </button>
        </div>
      )}
    </div>
  )
}
