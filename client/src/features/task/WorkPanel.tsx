/**
 * The task's work, beside the conversation (wide screens): what needs the
 * user, the steps in plain words, the files made, the web pages used. Calm by
 * default; Details (a per-browser pref) adds the tool calls and their times,
 * every file read and the run's stats.
 *
 * It covers the whole task, not one turn: the current turn's steps open,
 * earlier turns' steps folded under their question, and the files and sources
 * of every turn on the visible path.
 */

import { useMemo, useState } from "react"
import { Check, ChevronRight, Download, ExternalLink, X } from "lucide-react"
import type { ChangedFile, Part, Turn, TurnStats } from "@/api/types"
import { setPrefs, usePrefs } from "@/state/prefs"
import { ApprovalCard } from "@/features/chat/ApprovalCard"
import { FileLink } from "@/features/chat/FileLink"
import { FileBadge } from "@/features/task/FileBadge"
import { downloaded, sources, toSteps, type Step } from "@/features/task/steps"
import { formatBytes } from "@/lib/format"
import { clock } from "@/lib/time"
import { cn } from "@/lib/cn"

const seconds = (ms: number) => (ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : clock(ms))

function StepIcon({ status }: { status: Step["status"] }) {
  const ring = "relative z-10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
  if (status === "running")
    return <span className={cn(ring, "border border-border bg-card")}><span className="absolute -inset-px animate-spin rounded-full border-2 border-run border-r-transparent" /></span>
  if (status === "waiting") return <span className={cn(ring, "border border-ask bg-ask/15")}><span className="h-1.5 w-1.5 rounded-full bg-ask" /></span>
  if (status === "error") return <span className={cn(ring, "bg-destructive/10 text-destructive")}><X className="h-[11px] w-[11px]" strokeWidth={2.5} /></span>
  return <span className={cn(ring, "bg-ok/10 text-ok")}><Check className="h-[11px] w-[11px]" strokeWidth={2.5} /></span>
}

/** A panel section. With `count` it folds: open while short, folded past three items. */
function Section({ title, aside, count, children }: {
  title: string; aside?: React.ReactNode; count?: number; children: React.ReactNode
}) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const open = count === undefined || (userOpen ?? count <= 3)
  const head = "flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground"
  return (
    <section className="border-b px-4 py-3.5">
      {count === undefined ? (
        <h5 className={cn(head, "mb-2.5")}><span>{title}</span>{aside}</h5>
      ) : (
        <h5 className={cn(head, open && "mb-2.5")}>
          <button type="button" aria-expanded={open} onClick={() => setUserOpen(!open)}
                  className="flex w-full items-center gap-1 uppercase hover:text-foreground">
            <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} />
            {title}<span className="ml-auto font-mono normal-case tracking-normal">{count}</span>
          </button>
        </h5>
      )}
      {open && children}
    </section>
  )
}

function StepList({ steps, details }: { steps: Step[]; details: boolean }) {
  return (
    <ol>
      {steps.map((s, i) => (
        <li key={s.key + i} className="relative grid grid-cols-[1.25rem_1fr_auto] gap-2.5 py-[7px]">
          {i < steps.length - 1 && <span aria-hidden className="absolute left-2.5 top-7 -bottom-[7px] w-px bg-border" />}
          <StepIcon status={s.status} />
          <span className="min-w-0">
            <span className={cn("block text-sm font-medium", s.status === "error" && "text-destructive")}>{s.label}</span>
            {s.note && <span className="block text-xs text-muted-foreground">{s.note}</span>}
            {s.status === "waiting" && <span className="block text-xs text-muted-foreground">Waiting for you</span>}
            {details && s.detail.map((d, j) => (
              <span key={j} className="block truncate font-mono text-xs text-muted-foreground" title={d}>{d}</span>
            ))}
          </span>
          <span className="pt-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
            {details && s.ms !== undefined ? seconds(s.ms) : ""}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** One turn: its question, and opened, the steps it took. The newest starts open. */
function TurnSteps({ turn, steps, details, running, defaultOpen }: {
  turn: Turn; steps: Step[]; details: boolean; running: boolean; defaultOpen: boolean
}) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const open = userOpen ?? defaultOpen
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setUserOpen(!open)}
              className="flex w-full items-center gap-1.5 py-1 text-left text-sm text-muted-foreground hover:text-foreground">
        <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <span className={cn("min-w-0 flex-1 truncate", open && "text-foreground")} title={turn.user_text}>{turn.user_text || "Attachment"}</span>
        <span className="shrink-0 text-xs">{steps.length ? `${steps.length} step${steps.length === 1 ? "" : "s"}` : running ? "" : "answered"}</span>
      </button>
      {open && (
        <div className="mb-2 ml-1 mt-1">
          {steps.length ? <StepList steps={steps} details={details} />
            : <p className="pl-5 text-xs text-muted-foreground">{running ? "Getting started…" : "Answered directly, without using any tools."}</p>}
        </div>
      )}
    </div>
  )
}

function Tag({ children, tone }: { children: React.ReactNode; tone: "new" | "read" }) {
  return (
    <span className={cn("rounded-[5px] px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide",
                        tone === "new" ? "bg-ok/10 text-ok" : "bg-muted text-muted-foreground")}>
      {children}
    </span>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="font-display text-[15px] font-medium tabular-nums">{value}</div>
    </div>
  )
}

const compact = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

export interface PanelTurn { turn: Turn; parts: Part[]; stats: TurnStats | null; running: boolean }

export function WorkPanel({ chatId, turns }: { chatId: string; turns: PanelTurn[] }) {
  const { taskDetails: details, showStats } = usePrefs()
  const { parts, stats, running } = turns[turns.length - 1]
  const visible = (steps: Step[]) => (details ? steps : steps.filter((s) => !s.internal))
  const perTurn = useMemo(() => turns.map((t) => ({ ...t, steps: toSteps(t.parts, t.running) })), [turns])
  const pending = running ? parts.filter((p): p is Extract<Part, { kind: "approval" }> => p.kind === "approval" && p.status === "pending") : []
  const allParts = useMemo(() => turns.flatMap((t) => t.parts), [turns])
  const inputs = useMemo(() => downloaded(allParts), [allParts])
  // What the task made or changed, newest first, once each (a later turn's change replaces an
  // earlier entry). Only a file downloaded to be read is left out: an input, not a result.
  const made = useMemo(() => {
    const byName = new Map<string, ChangedFile>()
    for (const t of turns) for (const f of t.stats?.files ?? []) {
      byName.delete(f.name)
      byName.set(f.name, f)
    }
    return [...byName.values()].reverse().filter((f) => !(f.change === "created" && inputs.has(f.name)))
  }, [turns, inputs])
  const web = useMemo(() => sources(allParts), [allParts])
  const size = stats?.context_size ?? 0
  const used = stats?.context_used ?? 0

  return (
    <aside aria-label="Task progress"
           className="hidden w-[23.75rem] shrink-0 flex-col overflow-y-auto border-l bg-sidebar lg:flex">
      {pending.length > 0 && (
        <section className="space-y-2 border-b px-4 py-3.5">
          {pending.map((p) => <ApprovalCard key={p.id} part={p} live />)}
        </section>
      )}

      <Section title="Progress" aside={
        <button type="button" aria-pressed={details} onClick={() => setPrefs({ taskDetails: !details })}
                className={cn("text-[11px] font-medium normal-case tracking-normal underline underline-offset-[3px] hover:text-foreground",
                              details ? "text-foreground" : "text-muted-foreground")}>
          {details ? "Hide details" : "Show details"}
        </button>
      }>
        {perTurn.map((t, i) => (
          <TurnSteps key={t.turn.id} turn={t.turn} steps={visible(t.steps)} details={details} running={t.running}
                     defaultOpen={i === perTurn.length - 1} />
        ))}
      </Section>

      {made.length > 0 && (
        <Section title="Files" count={made.length}>
          <div className="grid gap-2">
            {made.map((f) => (
              <div key={f.name} className="grid grid-cols-[2.125rem_1fr_auto_auto] items-center gap-2.5 rounded-[10px] border bg-card p-2">
                <FileBadge name={f.name} />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium" title={f.name}>{f.name}</span>
                  <span className="block text-xs text-muted-foreground">{f.change === "created" ? "Made in this task" : "Changed"} · {formatBytes(f.size)}</span>
                </span>
                <Tag tone="new">{f.change === "created" ? "new" : "changed"}</Tag>
                <FileLink chatId={chatId} name={f.name} download title="Download"
                          className="flex h-8 w-8 items-center justify-center rounded-lg border bg-card text-muted-foreground hover:bg-accent hover:text-foreground">
                  <Download className="h-4 w-4" />
                </FileLink>
              </div>
            ))}
          </div>
        </Section>
      )}

      {web.length > 0 && (
        <Section title="Sources" count={web.length}>
          <ol>
            {web.map((s, i) => (
              <li key={s.url} className="grid grid-cols-[1.375rem_1fr] gap-2 py-1.5">
                <span className="pt-px font-mono text-[11px] font-medium text-muted-foreground">[{i + 1}]</span>
                <a href={s.url} target="_blank" rel="noreferrer noopener" className="group min-w-0">
                  <span className="line-clamp-2 text-sm group-hover:underline">{s.title}</span>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">{s.site}<ExternalLink className="h-3 w-3 opacity-0 group-hover:opacity-100" /></span>
                </a>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {details && showStats && stats && (stats.model_calls ?? 0) > 0 && (
        <section className="px-4 py-3.5">
          <h5 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">This run</h5>
          <div className="grid grid-cols-3 gap-2.5">
            <Stat label="Time" value={stats.duration_ms ? clock(stats.duration_ms) : "—"} />
            <Stat label="Model calls" value={String(stats.model_calls ?? 0)} />
            <Stat label="Speed" value={stats.tokens_per_second ? `${Math.round(stats.tokens_per_second)} tok/s` : "—"} />
            {size > 0 && (
              <div className="col-span-3">
                <div className="flex justify-between text-[11px] text-muted-foreground">
                  <span>Context</span><span className="font-mono">{compact(used)} of {compact(size)}</span>
                </div>
                <div className="mt-1.5 h-[3px] overflow-hidden rounded-full bg-muted">
                  <i className="block h-full rounded-full bg-run transition-[width]" style={{ width: `${Math.min(100, (used / size) * 100)}%` }} />
                </div>
              </div>
            )}
          </div>
        </section>
      )}
    </aside>
  )
}
