import { useState } from "react"
import { BookOpenText, Clock, Gauge, Sparkles, WholeWord, Wrench } from "lucide-react"
import type { TurnStats } from "@/api/types"
import { cn } from "@/lib/cn"
import { Tip } from "@/components/ui/tip"

/** Generation and reading stats, after llama.cpp's `ChatMessageStatistics`. */
export function Stats({ stats }: { stats: TurnStats }) {
  const [view, setView] = useState<"generation" | "reading">("generation")
  const seconds = (stats.duration_ms ?? 0) / 1000
  const time = seconds < 60 ? `${seconds.toFixed(1)}s` : `${Math.floor(seconds / 60)}min ${Math.round(seconds % 60)}s`
  return (
    <>
      <span className="inline-flex rounded-sm bg-muted-foreground/15 p-0.5">
        {([["generation", Sparkles, "Generation"], ["reading", BookOpenText, "Reading"]] as const).map(([id, Icon, label]) => (
          <Tip key={id} label={label}>
            <button type="button" onClick={() => setView(id)}
                    className={cn("flex h-5 w-5 items-center justify-center rounded-sm",
                                  view === id ? "bg-background text-foreground shadow-sm" : "")}>
              <Icon className="h-3 w-3" />
            </button>
          </Tip>
        ))}
      </span>
      {view === "generation" ? (
        <>
          <Badge icon={WholeWord}>{(stats.completion_tokens ?? 0).toLocaleString()} tokens</Badge>
          <Badge icon={Clock}>{time}</Badge>
          {stats.tokens_per_second ? <Badge icon={Gauge}>{stats.tokens_per_second.toFixed(2)} t/s</Badge> : null}
          {(stats.model_calls ?? 0) > 1 && <Badge icon={Wrench}>{stats.model_calls} model calls</Badge>}
        </>
      ) : (
        <>
          <Badge icon={WholeWord}>{(stats.prompt_tokens ?? 0).toLocaleString()} tokens</Badge>
          {stats.prompt_per_second ? <Badge icon={Gauge}>{stats.prompt_per_second.toFixed(2)} tokens/s</Badge> : null}
        </>
      )}
    </>
  )
}

function Badge({ icon: Icon, children }: { icon: typeof Clock; children: React.ReactNode }) {
  return <span className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5"><Icon className="h-3 w-3" />{children}</span>
}
