/** Under an answer: the page passages it quoted, numbered, highlighted on the page, or marked not found. */

import { useCallback, useContext, useEffect, useMemo, useState } from "react"
import { useAtlas } from "@/state/store"
import { AnswerExtras } from "@/state/slots"
import type { Turn } from "@/api/types"
import { cn } from "@/lib/cn"
import { tabCall } from "@ext/shared/tab"

// ------------------------------------------------------------ quote sources --

const QUOTE = /[“"]([^”"\n]{12,300})[”"]/g

/**
 * The passages an answer quoted, found on the page and highlighted; a click
 * scrolls to one. A quote the page does not contain is shown as such: with a
 * small model, that is how an unsupported claim becomes visible.
 */
export function QuoteSources({ turn, answer, tabId }: { turn: Turn; answer: string; tabId: number }) {
  const quotes = useMemo(() => Array.from(new Set(Array.from(answer.matchAll(QUOTE), (m) => m[1].trim()))).slice(0, 8), [answer])
  const latest = useAtlas((s) => s.chat?.turns.at(-1)?.id === turn.id)
  const [found, setFound] = useState<boolean[] | null>(null)
  const [active, setActive] = useState<number | null>(null)
  const extrasActive = useContext(AnswerExtras) !== null

  const check = useCallback(async () => {
    const result = await tabCall(tabId, "highlight", { quotes })
    setFound(Array.isArray(result.found) ? (result.found as boolean[]) : quotes.map(() => false))
  }, [quotes, tabId])

  useEffect(() => {
    if (latest && quotes.length && extrasActive) void check()
  }, [latest, quotes.length, extrasActive, check])

  if (!quotes.length) return null
  return (
    <div className="mt-3 flex flex-col gap-1.5">
      {quotes.map((q, i) => {
        const missing = found !== null && !found[i]
        return (
          <button key={q} type="button" disabled={missing}
                  onClick={async () => {
                    if (!found || !latest) await check()
                    await tabCall(tabId, "scrollToQuote", { index: i })
                    setActive(i)
                  }}
                  className={cn("flex gap-2 rounded-lg border px-2.5 py-2 text-left text-xs leading-snug transition-colors",
                                missing ? "cursor-default border-dashed text-muted-foreground"
                                  : active === i ? "border-run/40 bg-run/10" : "bg-card hover:bg-accent")}>
            <span className={cn("flex h-4 min-w-4 shrink-0 items-center justify-center rounded px-1 text-[11px] font-semibold",
                                missing ? "bg-muted" : "bg-run text-white")}>{i + 1}</span>
            <span className="min-w-0">
              “{q.length > 140 ? `${q.slice(0, 140)}…` : q}”
              {missing && <span className="ml-1 italic">not found in the page's text (it may be in an image)</span>}
            </span>
          </button>
        )
      })}
    </div>
  )
}
