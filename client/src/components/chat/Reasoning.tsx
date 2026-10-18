/**
 * Data parts: reasoning and the per-turn footer.
 *
 * These two are the only message parts that are not text or a tool call, and
 * both exist as `data-*` parts rather than as new primitives.
 */

import React from "react"
import { makeAssistantDataUI } from "@assistant-ui/react"
import { Brain, ChevronRight, RefreshCw } from "lucide-react"

import { atlas, useAtlas } from "@/services/atlasStore"
import { cn } from "@/lib/utils"

// ------------------------------------------------------------- reasoning --

interface ReasoningData {
  text: string
}

function ReasoningBlock({ text }: ReasoningData) {
  // Default open so the model's thoughts and reasoning are prominently visible
  const [open, setOpen] = React.useState(true)

  if (!text) return null

  return (
    <div className="mb-3 w-full rounded-2xl border border-border/80 bg-muted/20 overflow-hidden shadow-xs">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3.5 py-2.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground hover:bg-muted/40"
      >
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-primary" />
          <span className="font-semibold text-foreground">Thinking Process</span>
        </div>
        <ChevronRight
          className={cn("h-4 w-4 transition-transform duration-200", open && "rotate-90")}
        />
      </button>

      {open && (
        <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap border-t border-border/60 bg-background/50 p-3.5 font-mono text-xs leading-relaxed text-muted-foreground/90">
          {text}
        </pre>
      )}
    </div>
  )
}

export const ReasoningUI = makeAssistantDataUI<ReasoningData>({
  name: "reasoning",
  render: ({ data }) => <ReasoningBlock {...(data as ReasoningData)} />,
})

// ------------------------------------------------------------ turn footer --

interface TurnData {
  turnId: string
  version: number
  versionCount: number
  status: string
  usage: {
    input: number
    output: number
    total: number
    unreported: boolean
  } | null
}

/**
 * The version arrows and retry, for the turn this answer belongs to.
 */
function TurnFooter({ turnId, version, versionCount, status, usage }: TurnData) {
  const busy = useAtlas().busy
  const atStart = version <= 0
  const atEnd = version >= versionCount - 1

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground select-none">
      {versionCount > 1 && (
        <span className="flex items-center gap-0.5">
          <button
            onClick={() => atlas.selectVersion(turnId, -1)}
            disabled={busy || atStart}
            title="Previous version"
            className="flex h-5 w-5 items-center justify-center rounded transition-colors hover:bg-muted disabled:opacity-30"
          >
            <ChevronRight className="h-3.5 w-3.5 rotate-180" />
          </button>
          <span className="font-mono tabular-nums text-[11px]">
            {version + 1}/{versionCount}
          </span>
          <button
            onClick={() => atlas.selectVersion(turnId, +1)}
            disabled={busy || atEnd}
            title="Next version"
            className="flex h-5 w-5 items-center justify-center rounded transition-colors hover:bg-muted disabled:opacity-30"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </span>
      )}

      <button
        onClick={() => atlas.retry(turnId)}
        disabled={busy}
        title="Ask the same question again from the same state"
        className="flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors hover:bg-muted hover:text-foreground disabled:opacity-30"
      >
        <RefreshCw className="h-3 w-3" />
        <span>Retry</span>
      </button>

      <span className="font-mono opacity-60 text-[11px] px-1">{status}</span>

      {usage && (
        <span className="font-mono opacity-60 text-[11px]">
          {usage.unreported
            ? "· tokens not reported"
            : `· ${usage.total.toLocaleString()} tokens`}
        </span>
      )}
    </div>
  )
}

export const TurnFooterUI = makeAssistantDataUI<TurnData>({
  name: "turn",
  render: ({ data }) => <TurnFooter {...(data as TurnData)} />,
})

/** Mounts both registrations. Render once, inside the runtime provider. */
export const DataRenderers: React.FC = () => (
  <>
    <ReasoningUI />
    <TurnFooterUI />
  </>
)
