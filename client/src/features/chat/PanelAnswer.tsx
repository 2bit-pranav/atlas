/**
 * An answer in the browser extension's side panel: made to leave the most
 * room for the answer and for what points back at the page.
 *
 * - While it works: one box, the steps done and the thinking as one live line
 *   ("Show" opens the reasoning). Not a Reasoning block per model call.
 * - Once it answers: the work folds into one line ("Read the page · Found 3
 *   places"); a click opens the reasoning and the tool calls.
 * - No token counts, speeds, model names or times.
 */

import { useContext, useMemo, useState } from "react"
import { Check, ChevronRight, ChevronLeft, RefreshCw } from "lucide-react"
import type { Part, Turn, TurnStats } from "@/api/types"
import { atlas, useAtlas } from "@/state/store"
import { AnswerExtras } from "@/state/slots"
import { answerText } from "@/features/chat/transcript"
import { Markdown } from "@/features/chat/Markdown"
import { ToolGroup, type ToolPart } from "@/features/chat/ToolBlock"
import { ApprovalCard } from "@/features/chat/ApprovalCard"
import { ProducedFiles } from "@/features/chat/ProducedFiles"
import { Action, CopyButton } from "@/features/chat/MessageActions"
import { toSteps, workSummary } from "@/features/task/steps"
import { cn } from "@/lib/cn"

export function PanelAnswer({ turn, chatId, parts, stats, running, isLast }: {
  turn: Turn; chatId: string; parts: Part[]; stats: TurnStats | null; running: boolean; isLast: boolean
}) {
  const busy = useAtlas((s) => s.run !== null)
  const extras = useContext(AnswerExtras)
  const [open, setOpen] = useState(false)
  const steps = useMemo(() => toSteps(parts, running).filter((s) => !s.internal && s.key !== "answer"), [parts, running])
  const tools = parts.filter((p): p is ToolPart => p.kind === "tool")
  const reasoning = parts.filter((p) => p.kind === "reasoning").map((p) => (p as { text: string }).text).join("\n\n").trim()
  const texts = parts.filter((p) => p.kind === "text" || p.kind === "superseded")
  const approvals = parts.filter((p): p is Extract<Part, { kind: "approval" }> => p.kind === "approval")
  const answering = parts.some((p) => p.kind === "text")
  const working = running && !answering

  return (
    <div className="mt-3 w-full text-[13.5px] leading-relaxed">
      {working ? (
        <section aria-label="Atlas is working" className="flex flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5">
          {steps.map((s) => (
            <div key={s.key} className="flex items-center gap-2 text-[12.5px]">
              {s.status === "running" ? <Spinner /> : s.status === "waiting" ? <span className="h-2 w-2 shrink-0 rounded-full bg-ask" />
                : <Check className={cn("h-3.5 w-3.5 shrink-0", s.status === "error" ? "text-destructive" : "text-ok")} strokeWidth={2.6} />}
              <span className={cn("min-w-0 flex-1 truncate", s.status === "done" && "text-muted-foreground")}>{s.label}</span>
              {s.note && <span className="text-xs text-muted-foreground">{s.note}</span>}
            </div>
          ))}
          {!steps.some((s) => s.status === "running" || s.status === "waiting") && (
            <div className="flex items-center gap-2 text-[12.5px]">
              <Spinner />
              <span className="flex-1">{reasoning ? "Thinking" : "Reading the page"}</span>
              {reasoning && (
                <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
                        className="text-xs text-muted-foreground hover:text-foreground">{open ? "Hide" : "Show"}</button>
              )}
            </div>
          )}
          {reasoning && !open && (
            <p className="truncate pl-5 text-xs italic text-muted-foreground">{reasoning.split("\n").filter(Boolean).at(-1)}</p>
          )}
          {reasoning && open && (
            <div className="max-h-56 overflow-y-auto whitespace-pre-wrap border-l pl-3 text-xs text-muted-foreground">{reasoning}</div>
          )}
        </section>
      ) : (steps.length > 0 || reasoning) && (
        <div>
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
                  className="flex max-w-full items-center gap-1.5 py-0.5 text-left text-xs text-muted-foreground hover:text-foreground">
            <Check className={cn("h-3.5 w-3.5 shrink-0", steps.some((s) => s.status === "error") ? "text-ask" : "text-ok")} strokeWidth={2.6} />
            <span className="truncate">{workSummary(steps.map((s) => s.label))}</span>
            <ChevronRight className={cn("h-3 w-3 shrink-0 transition-transform", open && "rotate-90")} />
          </button>
          {open && (
            <div className="mb-2 mt-1 flex flex-col gap-2 border-l pl-3">
              {reasoning && <div className="max-h-56 overflow-y-auto whitespace-pre-wrap text-xs text-muted-foreground">{reasoning}</div>}
              {tools.length > 0 && <ToolGroup parts={tools} defaultOpen={false} />}
            </div>
          )}
        </div>
      )}

      {approvals.map((p) => <ApprovalCard key={p.id} part={p} live={running} />)}

      <div className={cn(texts.length > 0 && "mt-1.5")}>
        {texts.map((p, i) => p.kind === "superseded" ? null : <Markdown key={i} text={(p as { text: string }).text} />)}
      </div>

      {!running && turn.status !== "completed" && (
        <p className={cn("mt-2 text-xs italic", turn.status === "failed" ? "text-destructive" : "text-muted-foreground")}>
          {turn.status === "cancelled" ? "Stopped." : turn.status === "interrupted" ? "Interrupted: Atlas restarted during this answer."
            : turn.error ?? "This answer failed."}
          {isLast && " Try again, or ask differently."}
        </p>
      )}

      {!running && stats?.files && stats.files.length > 0 && <ProducedFiles files={stats.files} chatId={chatId} />}
      {!running && extras && turn.status === "completed" && extras(turn, answerText(parts))}

      {!running && (
        <div className="mt-1 flex h-7 items-center gap-1 text-muted-foreground">
          {turn.versions.length > 1 && (
            <span className="flex items-center gap-0.5">
              <Action label="Previous version" disabled={busy || turn.version <= 0} onClick={() => void atlas.selectVersion(turn.id, -1)}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Action>
              <span className="font-mono text-[11px] tabular-nums">{turn.version + 1}/{turn.versions.length}</span>
              <Action label="Next version" disabled={busy || turn.version >= turn.versions.length - 1} onClick={() => void atlas.selectVersion(turn.id, +1)}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Action>
            </span>
          )}
          <CopyButton text={answerText(parts)} />
          {isLast && (
            <Action label="Answer again" disabled={busy} onClick={() => void atlas.retry(turn.id)}>
              <RefreshCw className="h-3 w-3" />
            </Action>
          )}
        </div>
      )}
    </div>
  )
}

function Spinner() {
  return <span aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-run border-r-transparent" />
}
