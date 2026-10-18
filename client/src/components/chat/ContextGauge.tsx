/**
 * How full the context window is, after llama.cpp's `ChatFormContextGauge`:
 * a 20px ring in the composer, with the details on hover. Muted below 80%,
 * amber from 80%, red from 95%.
 *
 * "Used" is everything in the llama.cpp slot after the latest model call: the
 * cached prefix, the newly read prompt and what was generated. It moves while
 * an answer streams, because the backend forwards per-token timings.
 */

import { useRef, useState } from "react"
import { createPortal } from "react-dom"

import { currentStats, useAtlas } from "@/lib/store"
import { cn } from "@/lib/utils"

const compact = (n: number) =>
  n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K` : String(n)

export function ContextGauge() {
  const stats = useAtlas(currentStats)
  const fallbackSize = useAtlas((s) => Number(s.settings?.values["model.context_size"] ?? 0))
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const open = anchor !== null
  const show = () => setAnchor(button.current?.getBoundingClientRect() ?? null)
  const hide = () => setAnchor(null)

  const size = stats?.context_size || fallbackSize
  const used = stats?.context_used ?? 0
  if (!size || !used) return null

  const ratio = Math.min(1, used / size)
  const tone = ratio >= 0.95 ? "text-red-400" : ratio >= 0.8 ? "text-amber-400" : "text-muted-foreground"
  const bar = ratio >= 0.95 ? "bg-red-400" : ratio >= 0.8 ? "bg-amber-400" : "bg-emerald-500"
  const r = 8
  const circumference = 2 * Math.PI * r

  return (
    <div onMouseEnter={show} onMouseLeave={hide}>
      <button ref={button} type="button" onClick={() => (open ? hide() : show())} aria-label="Context usage"
              className={cn("flex h-8 w-8 items-center justify-center rounded-full hover:bg-muted-foreground/10", tone)}>
        <svg width="20" height="20" viewBox="0 0 20 20" className="-rotate-90">
          <circle cx="10" cy="10" r={r} fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="2.5" />
          <circle cx="10" cy="10" r={r} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
                  strokeDasharray={circumference} strokeDashoffset={circumference * (1 - ratio)} />
        </svg>
      </button>

      {/* Portalled to <body>: the composer clips its children (overflow-hidden,
          for the rounded pill), which cut this popover off. Fixed position,
          anchored above the ring's right edge. */}
      {anchor && createPortal(
        <div
          style={{ bottom: window.innerHeight - anchor.top + 8, right: Math.max(8, window.innerWidth - anchor.right) }}
          className="fixed z-50 w-64 rounded-lg border border-border/50 bg-popover p-3 text-sm text-popover-foreground shadow-lg ring-1 ring-foreground/10">
          <div className="flex items-baseline justify-between">
            <span className="font-medium">Context</span>
            <span className="font-mono text-xs text-muted-foreground">{compact(used)} / {compact(size)}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <div className={cn("h-full rounded-full", bar)} style={{ width: `${ratio * 100}%` }} />
          </div>
          <div className="mt-1.5 flex justify-between text-xs text-muted-foreground">
            <span><span className="font-semibold text-foreground">{Math.round(ratio * 100)}%</span> used</span>
            <span>{compact(Math.max(0, size - used))} remaining</span>
          </div>

          <p className="mt-3 text-[11px] uppercase tracking-wide text-muted-foreground/70">Last model call</p>
          <dl className="mt-1 space-y-0.5 text-xs">
            <Row label="Prompt" value={`${(stats?.prompt_tokens ?? 0).toLocaleString()} tok`} />
            <Row label="Generated" value={`${(stats?.completion_tokens ?? 0).toLocaleString()} tok`} />
            {stats?.prompt_per_second ? <Row label="Reading" value={`${stats.prompt_per_second.toFixed(1)} t/s`} /> : null}
            {stats?.tokens_per_second ? <Row label="Writing" value={`${stats.tokens_per_second.toFixed(1)} t/s`} /> : null}
            {stats?.model_calls && stats.model_calls > 1 ? <Row label="Model calls this turn" value={String(stats.model_calls)} /> : null}
          </dl>
        </div>,
        document.body,
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  )
}
