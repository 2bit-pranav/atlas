import { useContext, useState } from "react"
import { ChevronLeft, ChevronRight, Download, RefreshCw } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import { usePrefs } from "@/state/prefs"
import { FileLink } from "@/features/chat/FileLink"
import type { ChangedFile, Part, Turn, TurnStats } from "@/api/types"
import { answerText } from "@/features/chat/transcript"
import { cn } from "@/lib/cn"
import { Markdown } from "@/features/chat/Markdown"
import { formatBytes } from "@/lib/format"
import { ToolGroup, type ToolPart } from "@/features/chat/ToolBlock"
import { Tip } from "@/components/ui/tip"
import { AnswerExtras } from "@/state/slots"
import { Reasoning } from "@/features/chat/Reasoning"
import { ApprovalCard } from "@/features/chat/ApprovalCard"
import { Stats } from "@/features/chat/StatsBar"
import { Action, CopyButton } from "@/features/chat/MessageActions"

/** An answer given up on after a failure, before Atlas sent the model back to work. */
function Superseded({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="my-2">
      <button type="button" onClick={() => setOpen(!open)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        Earlier attempt, replaced after a tool failed and the model tried again
      </button>
      {open && <div className="mt-1 border-l pl-3 text-sm text-muted-foreground line-through decoration-muted-foreground/40"><Markdown text={text} /></div>}
    </div>
  )
}

/** Files this answer created or changed, to download. */
function ProducedFiles({ files, chatId }: { files: ChangedFile[]; chatId: string }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {files.map((f) => {
        const ext = f.name.includes(".") ? f.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
        return (
          <div key={f.name} className="flex items-center gap-3 rounded-lg border bg-muted p-2 pr-1.5">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">{ext}</span>
            <span className="min-w-0">
              <span className="block max-w-48 truncate text-sm font-medium" title={f.name}>{f.name}</span>
              <span className="block text-xs text-muted-foreground">{f.change === "created" ? "Created" : "Updated"} · {formatBytes(f.size)}</span>
            </span>
            <Tip label="Download">
              <FileLink chatId={chatId} name={f.name} download
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground">
                <Download className="h-3.5 w-3.5" />
              </FileLink>
            </Tip>
          </div>
        )
      })}
    </div>
  )
}

/** Parts as they are drawn: a run of consecutive tool calls is one item. */
type Item = { tools: ToolPart[]; index: number } | { part: Exclude<Part, ToolPart>; index: number }

function items(parts: Part[]): Item[] {
  const out: Item[] = []
  parts.forEach((part, index) => {
    const last = out[out.length - 1]
    if (part.kind !== "tool") out.push({ part, index })
    else if (last && "tools" in last) last.tools.push(part)
    else out.push({ tools: [part], index })
  })
  return out
}

// ------------------------------------------------------------- assistant --

export function AssistantMessage({ turn, chatId, parts, stats, running, isLast }: {
  turn: Turn; chatId: string; parts: Part[]; stats: TurnStats | null; running: boolean; isLast: boolean
}) {
  const prefs = usePrefs()
  const busy = useAtlas((s) => s.run !== null)
  const currentModel = useAtlas((s) => String(s.settings?.values["model.name"] ?? ""))
  // The model that wrote this version, falling back to the current one for
  // turns recorded before models were stored.
  const modelName = stats?.model ?? currentModel
  const empty = parts.length === 0
  const lastIndex = parts.length - 1
  const extras = useContext(AnswerExtras)

  return (
    <div className="mt-6 w-full text-[15px] leading-[1.875rem]">
      {running && empty && <span className="shimmer-text text-sm">Processing...</span>}

      {items(parts).map((item) => {
        if ("tools" in item)
          return <ToolGroup key={item.tools[0].id || item.index} parts={item.tools} defaultOpen={prefs.expandTools} />
        const { part, index: i } = item
        if (part.kind === "reasoning")
          return <Reasoning key={i} text={part.text} streaming={running && i === lastIndex}
                            interrupted={!running && turn.status !== "completed"} defaultOpen={prefs.expandReasoning} />
        if (part.kind === "approval")
          return <ApprovalCard key={part.id} part={part} live={running} />
        if (part.kind === "superseded")
          return <Superseded key={i} text={part.text} />
        return <Markdown key={i} text={part.text} />
      })}

      {!running && turn.status !== "completed" && (
        <p className={cn("mt-3 text-xs italic", turn.status === "failed" ? "text-destructive" : "text-muted-foreground")}>
          {turn.status === "cancelled" ? "Stopped." :
           turn.status === "interrupted" ? "Interrupted: the backend restarted during this answer." :
           turn.error ?? "This answer failed."}
          {isLast && " Regenerate or edit the question to continue."}
        </p>
      )}

      {!running && stats?.files && stats.files.length > 0 && <ProducedFiles files={stats.files} chatId={chatId} />}

      {!running && extras && turn.status === "completed" && extras(turn, answerText(parts))}

      {!running && (
        <>
          {prefs.showStats && stats && (stats.completion_tokens ?? 0) > 0 && (
            <div className="my-4 inline-flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {modelName && <span className="rounded-sm bg-muted px-1.5 py-0.5 font-medium">{modelName}</span>}
              <Stats stats={stats} />
            </div>
          )}
          <div className="mt-2 flex h-6 items-center gap-2">
            {turn.versions.length > 1 && (
              <span className="flex items-center gap-0.5">
                <Action label="Previous version" disabled={busy || turn.version <= 0}
                        onClick={() => void atlas.selectVersion(turn.id, -1)}>
                  <ChevronLeft className="h-4 w-4" />
                </Action>
                <span className="font-mono text-xs tabular-nums text-muted-foreground">{turn.version + 1}/{turn.versions.length}</span>
                <Action label="Next version" disabled={busy || turn.version >= turn.versions.length - 1}
                        onClick={() => void atlas.selectVersion(turn.id, +1)}>
                  <ChevronRight className="h-4 w-4" />
                </Action>
              </span>
            )}
            <CopyButton text={answerText(parts)} />
            {isLast && (
              <Action label="Regenerate" disabled={busy} onClick={() => void atlas.retry(turn.id)}>
                <RefreshCw className="h-3 w-3" />
              </Action>
            )}
          </div>
        </>
      )}
    </div>
  )
}
