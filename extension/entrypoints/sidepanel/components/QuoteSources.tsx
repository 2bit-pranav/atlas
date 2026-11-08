/**
 * Under an answer: the places on the page it pointed at (its quotes, and the
 * elements it named by ref), each a button that takes the user there.
 *
 * Found ones are highlighted on the page; Go to scrolls to one and marks it,
 * the arrows step through them. A quote the page does not hold is shown as not
 * found: with a small model, that is how an unsupported claim becomes visible.
 * For "find" and "where" questions the first place is gone to at once. A time
 * in a video ("[12:34]") plays it from there; never on its own.
 */

import { useCallback, useContext, useEffect, useMemo, useState } from "react"
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react"
import { useAtlas } from "@/state/store"
import { AnswerExtras } from "@/state/slots"
import type { Turn } from "@/api/types"
import { cn } from "@/lib/cn"
import { tabCall } from "@ext/shared/tab"
import type { Place } from "@ext/page/highlight"
import { pointers, wantsToGo } from "@ext/page/pointers"

export function QuoteSources({ turn, answer, tabId }: { turn: Turn; answer: string; tabId: number }) {
  const targets = useMemo(() => pointers(answer), [answer])
  const latest = useAtlas((s) => s.chat?.turns.at(-1)?.id === turn.id)
  const [places, setPlaces] = useState<Place[] | null>(null)
  const [active, setActive] = useState<number | null>(null)
  const extrasActive = useContext(AnswerExtras) !== null

  const locate = useCallback(async () => {
    const result = await tabCall(tabId, "point", { pointers: targets })
    const found = Array.isArray(result.places) ? (result.places as Place[]) : targets.map(() => null)
    setPlaces(found.map((p, i) => p ?? { found: false, how: "none" as const, kind: "Text", text: "quote" in targets[i] ? targets[i].quote : "" }))
    return found as (Place | null)[]
  }, [targets, tabId])

  const goTo = useCallback(async (i: number) => {
    if (!places || !latest) await locate()   // an older answer: its places were not marked yet
    const r = await tabCall(tabId, "go", { index: i })
    if (r.ok) setActive(i)
  }, [places, latest, locate, tabId])

  useEffect(() => {
    if (!latest || !targets.length || !extrasActive) return
    void locate().then((found) => {
      const first = found.findIndex((p, i) => p?.found && !("time" in targets[i]))   // a video never starts on its own
      if (first >= 0 && (wantsToGo(turn.user_text) || targets.some((t) => "ref" in t))) void tabCall(tabId, "go", { index: first }).then((r) => r.ok && setActive(first))
    })
  }, [latest, targets, extrasActive, locate, tabId, turn.user_text])

  if (!targets.length) return null
  const found = (places ?? []).map((p, i) => (p.found ? i : -1)).filter((i) => i >= 0)
  const step = (dir: 1 | -1) => {
    if (!found.length) return
    const at = active === null ? -1 : found.indexOf(active)
    void goTo(found[(at + dir + found.length) % found.length])
  }

  return (
    <section aria-label="Places on the page" className="mt-2.5 overflow-hidden rounded-xl border">
      <div className="flex items-center gap-1.5 border-b bg-muted/40 py-1.5 pl-3 pr-1.5">
        <span className="flex-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">On this page</span>
        {found.length > 1 && (
          <>
            <span className="text-xs tabular-nums text-muted-foreground">
              {active !== null && found.includes(active) ? `${found.indexOf(active) + 1} of ${found.length}` : `${found.length} places`}
            </span>
            <button type="button" aria-label="Previous place" onClick={() => step(-1)} className={ARROW}><ChevronUp className="h-3.5 w-3.5" /></button>
            <button type="button" aria-label="Next place" onClick={() => step(1)} className={ARROW}><ChevronDown className="h-3.5 w-3.5" /></button>
          </>
        )}
      </div>
      {targets.map((t, i) => {
        const place = places?.[i]
        const missing = place !== undefined && place !== null && !place.found
        const isActive = active === i
        return (
          <div key={i} className={cn("flex gap-2.5 border-t px-3 py-2 first:border-t-0", isActive && "bg-run/10 shadow-[inset_3px_0_0_0_oklch(var(--run))]")}>
            <span className={cn("mt-0.5 flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded text-[11px] font-semibold",
                                isActive ? "bg-run text-white" : "bg-muted text-foreground/80")}>{i + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span>{place?.kind ?? ("ref" in t ? "Element" : "time" in t ? "Video" : "Passage")}</span>
                {place?.how === "exact" && <span className="rounded bg-ok/15 px-1 text-ok">Exact</span>}
                {place?.how === "similar" && <span className="rounded bg-ask/15 px-1 text-ask">Similar</span>}
                {missing && <span className="italic">{"ref" in t ? "not on the page now" : "time" in t ? "no video on the page" : "not found on the page"}</span>}
              </div>
              <p className={cn("line-clamp-2 text-[12.5px] leading-snug", missing && "text-muted-foreground line-through decoration-muted-foreground/40")}>
                {place?.text || ("quote" in t ? `“${t.quote}”` : "ref" in t ? t.ref : t.label)}
              </p>
            </div>
            {!missing && (
              <div className="flex shrink-0 items-center gap-1 self-center">
                <button type="button" onClick={() => void goTo(i)}
                        className={cn("h-7 rounded-md px-2.5 text-xs font-medium", isActive ? "bg-primary text-primary-foreground" : "border bg-card hover:bg-accent")}>
                  {"ref" in t ? "Show" : "time" in t ? "Play from here" : "Go to"}
                </button>
                {place?.href && /^https?:/i.test(place.href) && (
                  <button type="button" aria-label="Open the link" onClick={() => void browser.tabs.create({ url: place.href! })}
                          className="flex h-7 w-7 items-center justify-center rounded-md border bg-card hover:bg-accent">
                    <ExternalLink className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            )}
          </div>
        )
      })}
    </section>
  )
}

const ARROW = "flex h-6 w-6 items-center justify-center rounded-md border bg-card text-muted-foreground hover:bg-accent hover:text-foreground"
