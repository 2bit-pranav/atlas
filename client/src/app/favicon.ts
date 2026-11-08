/**
 * The tab's icon says what Atlas is doing: the "A" mark, plus a dot in the
 * corner while a task works (blue, pulsing), needs the user (amber: an
 * approval auto-rejects), or finished while the tab was in the background
 * (green, until the tab is looked at).
 *
 * Browsers do not animate SVG favicons, so the pulse swaps two icons.
 * shortcut: background tabs throttle timers, so the pulse may stutter there; the colour is what matters.
 */

import { useEffect, useRef, useState } from "react"
import { useAtlas } from "@/state/store"

type Dot = "run" | "ask" | "ok" | null

const COLOR = { run: "#3b82f6", ask: "#f59e0b", ok: "#10b981" }

export function icon(dot: Dot, dim = false): string {
  const mark = "<rect width='32' height='32' rx='8' fill='#171717'/>" +
    "<path d='M9.5 24 15 8h2l5.5 16h-3l-1.3-4h-4.4l-1.3 4zm5.1-6.6h2.8L16 13z' fill='#fafafa' fill-rule='evenodd'/>"
  const badge = dot ? `<circle cx='26' cy='26' r='6.5' fill='#fff'/><circle cx='26' cy='26' r='5' fill='${COLOR[dot]}' opacity='${dim ? 0.35 : 1}'/>` : ""
  return `data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>${mark}${badge}</svg>`)}`
}

function setIcon(href: string) {
  let link = document.querySelector<HTMLLinkElement>("link[rel='icon']")
  if (!link) {
    link = document.createElement("link")
    link.rel = "icon"
    document.head.appendChild(link)
  }
  if (link.href !== href) link.href = href
}

export function useFavicon() {
  const running = useAtlas((s) => s.run !== null)
  const waiting = useAtlas((s) => Boolean(s.live?.parts.some((p) => p.kind === "approval" && p.status === "pending")))
  const [unseen, setUnseen] = useState(false)
  const wasRunning = useRef(false)

  // A run that ends while the tab is hidden leaves a green dot until the tab is seen.
  useEffect(() => {
    if (wasRunning.current && !running && document.hidden) setUnseen(true)
    wasRunning.current = running
  }, [running])
  useEffect(() => {
    const seen = () => { if (!document.hidden) setUnseen(false) }
    document.addEventListener("visibilitychange", seen)
    return () => document.removeEventListener("visibilitychange", seen)
  }, [])

  const dot: Dot = running ? (waiting ? "ask" : "run") : unseen ? "ok" : null
  useEffect(() => {
    setIcon(icon(dot))
    if (dot !== "run") return
    let dim = false
    const timer = setInterval(() => { dim = !dim; setIcon(icon("run", dim)) }, 600)
    return () => clearInterval(timer)
  }, [dot])
}
