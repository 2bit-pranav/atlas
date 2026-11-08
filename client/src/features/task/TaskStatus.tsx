import { useEffect, useState } from "react"
import type { Part, Turn, TurnStats } from "@/api/types"
import { cn } from "@/lib/cn"
import { clock } from "@/lib/time"

const LOOK = {
  run: { pill: "bg-run/10 text-run", dot: "bg-run animate-pulse" },
  ask: { pill: "bg-ask/15 text-ask", dot: "bg-ask" },
  ok: { pill: "bg-ok/10 text-ok", dot: "bg-ok" },
  bad: { pill: "bg-destructive/10 text-destructive", dot: "bg-destructive" },
  idle: { pill: "bg-muted text-muted-foreground", dot: "bg-muted-foreground/50" },
}

const ENDED: Record<string, [string, keyof typeof LOOK]> = {
  completed: ["Done", "ok"], cancelled: ["Stopped", "idle"], failed: ["Failed", "bad"], interrupted: ["Interrupted", "bad"],
}

/** "Working · 0:24", "Needs you · 0:31", "Done · 0:41": a turn's state and how long it ran. */
export function TaskStatus({ turn, parts, stats }: { turn: Turn; parts: Part[]; stats: TurnStats | null }) {
  const running = turn.status === "running"
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const waiting = running && parts.some((p) => p.kind === "approval" && p.status === "pending")
  const [label, tone] = running ? (waiting ? ["Needs you", "ask" as const] : ["Working", "run" as const])
    : ENDED[turn.status] ?? ["Done", "ok" as const]
  const ms = running ? now - turn.created_at : stats?.duration_ms
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", LOOK[tone].pill)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", LOOK[tone].dot)} />
      {label}{ms ? <span className="tabular-nums"> · {clock(ms)}</span> : null}
    </span>
  )
}
