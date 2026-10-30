/** Under an answer: the page passages it quoted, highlighted or marked not found. */

import { useCallback, useContext, useEffect, useMemo, useState } from "react"
import { useAtlas } from "@/state/store"
import { AnswerExtras } from "@/state/slots"
import type { Turn } from "@/api/types"
import { cn } from "@/lib/cn"
import { tabCall } from "@ext/shared/tab"

// ------------------------------------------------------------ quote sources --

const QUOTE = /[“"]([^”"\n]{12,300})[”"]/g

/**
 * The passages an answer quoted, found on the page and highlighted. A quote
 * the page does not contain is shown as such: with a small model, that is
 * how an unsupported claim becomes visible.
 */
export function QuoteSources({ turn, answer, tabId }: { turn: Turn; answer: string; tabId: number }) {
  const quotes = useMemo(() => Array.from(new Set(Array.from(answer.matchAll(QUOTE), (m) => m[1].trim()))).slice(0, 8), [answer])
  const latest = useAtlas((s) => s.chat?.turns.at(-1)?.id === turn.id)
  const [found, setFound] = useState<boolean[] | null>(null)
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
    <div className="mt-3 rounded-lg border bg-muted/30 p-2 text-xs">
      <p className="mb-1.5 font-medium text-muted-foreground">On this page</p>
      <ul className="space-y-1">
        {quotes.map((q, i) => {
          const ok = found?.[i]
          return (
            <li key={q}>
              <button type="button" disabled={found !== null && !ok}
                      onClick={async () => {
                        if (!found || !latest) await check()
                        await tabCall(tabId, "scrollToQuote", { index: i })
                      }}
                      className={cn("w-full rounded-md px-2 py-1 text-left leading-snug hover:bg-accent disabled:cursor-default disabled:hover:bg-transparent",
                                    found !== null && !ok && "text-destructive")}>
                <span className="mr-1">{found === null ? "·" : ok ? "✓" : "✗"}</span>
                “{q.length > 110 ? `${q.slice(0, 110)}…` : q}”
                {found !== null && !ok && <span className="ml-1 italic">not in the page's text (may be from an image)</span>}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
