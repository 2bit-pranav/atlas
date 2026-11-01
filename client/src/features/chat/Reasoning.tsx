import { memo, useEffect, useRef, useState } from "react"
import { ChevronDown, Lightbulb } from "lucide-react"
import { cn } from "@/lib/cn"

/** Reasoning, after llama.cpp's `ChatMessageReasoningBlock`. */
export const Reasoning = memo(function Reasoning({ text, streaming, interrupted, defaultOpen }: {
  text: string; streaming: boolean; interrupted: boolean; defaultOpen: boolean
}) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const open = userOpen ?? (streaming || defaultOpen)
  const body = useRef<HTMLDivElement>(null)

  // While thinking streams, keep the newest line in view.
  useEffect(() => {
    if (streaming && open && body.current) body.current.scrollTop = body.current.scrollHeight
  }, [text, streaming, open])

  return (
    <div className="my-2">
      <button type="button" onClick={() => setUserOpen(!open)} className="group flex items-center gap-2 py-1">
        <Lightbulb className="h-3.5 w-3.5 text-muted-foreground/60" />
        <span className={cn("text-sm font-medium text-foreground/80", streaming && "shimmer-text")}>
          {streaming ? "Reasoning..." : "Reasoning"}
        </span>
        {interrupted && <span className="text-xs italic text-muted-foreground/70">Interrupted</span>}
        <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground opacity-0 transition-all group-hover:opacity-100",
                                   open && "rotate-180")} />
      </button>
      {open && (
        <div className="pl-1.5">
          <div ref={body} className={cn("my-2 whitespace-pre-wrap border-l border-muted-foreground/20 pl-4 text-[13px] leading-relaxed text-muted-foreground",
                                        streaming && "max-h-[28rem] overflow-y-auto")}>
            {text}
          </div>
        </div>
      )}
    </div>
  )
})
