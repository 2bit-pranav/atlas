/**
 * The task's work, beside the conversation (wide screens): what needs the
 * user, the steps in plain words, the files made, the web pages used. Calm by
 * default; Details (a per-browser pref) adds the tool calls, every file read
 * and the run's stats.
 *
 * It covers the whole task, not one turn: the current turn's steps open,
 * earlier turns' steps folded under their question, and the files and sources
 * of every turn on the visible path.
 */

import { useMemo, useState } from "react"
import { Check, ChevronRight, Download, ExternalLink, Loader2, X } from "lucide-react"
import type { ChangedFile, Part, Turn, TurnStats } from "@/api/types"
import { setPrefs, usePrefs } from "@/state/prefs"
import { ApprovalCard } from "@/features/chat/ApprovalCard"
import { FileLink } from "@/features/chat/FileLink"
import { Stats } from "@/features/chat/StatsBar"
import { readFiles, sources, toSteps, type Step } from "@/features/task/steps"
import { formatBytes } from "@/lib/format"
import { cn } from "@/lib/cn"

function statusOf(turn: Turn, running: boolean, waiting: boolean): { label: string; tone: string } {
  if (running) return waiting ? { label: "Needs you", tone: "ask" } : { label: "Working", tone: "run" }
  return {
    completed: { label: "Done", tone: "ok" },
    cancelled: { label: "Stopped", tone: "idle" },
    failed: { label: "Failed", tone: "bad" },
    interrupted: { label: "Interrupted", tone: "bad" },
    running: { label: "Working", tone: "run" },
  }[turn.status]
}

const TONE: Record<string, string> = {
  run: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  ask: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  ok: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  bad: "bg-destructive/10 text-destructive",
  idle: "bg-muted text-muted-foreground",
}

function StepIcon({ status }: { status: Step["status"] }) {
  const ring = "relative z-10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
  if (status === "running") return <span className={cn(ring, "bg-background text-sky-600 dark:text-sky-400")}><Loader2 className="h-4 w-4 animate-spin" /></span>
  if (status === "waiting") return <span className={cn(ring, "border border-amber-500 bg-amber-500/15")}><span className="h-1.5 w-1.5 rounded-full bg-amber-500" /></span>
  if (status === "error") return <span className={cn(ring, "bg-destructive/10 text-destructive")}><X className="h-3 w-3" strokeWidth={3} /></span>
  return <span className={cn(ring, "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400")}><Check className="h-3 w-3" strokeWidth={3} /></span>
}

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2.5 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>{title}</span>{aside}
      </h3>
      {children}
    </section>
  )
}

const ext = (name: string) => (name.includes(".") ? name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE")

function StepList({ steps, details }: { steps: Step[]; details: boolean }) {
  return (
    <ol className="relative">
      {steps.map((s, i) => (
        <li key={s.key + i} className="relative flex gap-3 pb-3 last:pb-0">
          {i < steps.length - 1 && <span aria-hidden className="absolute left-2.5 top-6 -bottom-0.5 w-px bg-border" />}
          <StepIcon status={s.status} />
          <span className="min-w-0 pt-px">
            <span className={cn("block text-sm", s.status === "error" && "text-destructive")}>{s.label}</span>
            {s.note && <span className="block text-xs text-muted-foreground">{s.note}</span>}
            {details && s.detail.map((d, j) => (
              <span key={j} className="block truncate font-mono text-[11px] text-muted-foreground" title={d}>{d}</span>
            ))}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** An earlier turn: its question, folded; opened, the steps it took. */
function Earlier({ turn, steps, details }: { turn: Turn; steps: Step[]; details: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
              className="flex w-full items-center gap-1.5 py-1 text-left text-sm text-muted-foreground hover:text-foreground">
        <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <span className="min-w-0 flex-1 truncate" title={turn.user_text}>{turn.user_text || "Attachment"}</span>
        <span className="shrink-0 text-xs">{steps.length ? `${steps.length} step${steps.length === 1 ? "" : "s"}` : "answered"}</span>
      </button>
      {open && steps.length > 0 && <div className="mb-2 ml-1 mt-1.5"><StepList steps={steps} details={details} /></div>}
    </div>
  )
}

export interface PanelTurn { turn: Turn; parts: Part[]; stats: TurnStats | null; running: boolean }

export function WorkPanel({ chatId, turns }: { chatId: string; turns: PanelTurn[] }) {
  const { taskDetails: details, showStats } = usePrefs()
  const current = turns[turns.length - 1]
  const { turn, parts, stats, running } = current
  const visible = (steps: Step[]) => (details ? steps : steps.filter((s) => !s.internal))
  const steps = useMemo(() => toSteps(parts, running), [parts, running])
  const shown = visible(steps)
  const earlier = useMemo(() => turns.slice(0, -1).map((t) => ({ turn: t.turn, steps: toSteps(t.parts, false) })), [turns])
  const pending = running ? parts.filter((p): p is Extract<Part, { kind: "approval" }> => p.kind === "approval" && p.status === "pending") : []
  const allParts = useMemo(() => turns.flatMap((t) => t.parts), [turns])
  const read = useMemo(() => readFiles(allParts), [allParts])
  // What the task made, newest first, once each (a later turn's change replaces an earlier entry).
  // A PDF read_pdf downloaded is an input, not something the task made.
  const made = useMemo(() => {
    const byName = new Map<string, ChangedFile>()
    for (const t of turns) for (const f of t.stats?.files ?? []) {
      byName.delete(f.name)
      byName.set(f.name, f)
    }
    return [...byName.values()].reverse().filter((f) => !read.includes(f.name))
  }, [turns, read])
  const web = useMemo(() => sources(allParts), [allParts])
  const status = statusOf(turn, running, pending.length > 0)

  return (
    <aside aria-label="Task progress"
           className="hidden w-[22rem] shrink-0 flex-col gap-6 overflow-y-auto border-l px-5 py-6 lg:flex">
      {pending.map((p) => <ApprovalCard key={p.id} part={p} live />)}

      <Section title="Progress" aside={
        <button type="button" aria-pressed={details} onClick={() => setPrefs({ taskDetails: !details })}
                className="text-[11px] font-medium normal-case tracking-normal text-muted-foreground underline underline-offset-2 hover:text-foreground">
          {details ? "Hide details" : "Details"}
        </button>
      }>
        {earlier.length > 0 && (
          <div className="mb-4 border-b pb-3">
            {earlier.map((e) => <Earlier key={e.turn.id} turn={e.turn} steps={visible(e.steps)} details={details} />)}
          </div>
        )}
        <span className={cn("mb-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", TONE[status.tone])}>
          {running && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}{status.label}
        </span>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">{running ? "Getting started…" : "Answered directly, without using any tools."}</p>
        ) : <StepList steps={shown} details={details} />}
      </Section>

      {(made.length > 0 || read.length > 0) && (
        <Section title="Files">
          <div className="space-y-2">
            {made.map((f) => (
              <div key={f.name} className="flex items-center gap-3 rounded-lg border bg-card p-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 font-mono text-[10px] font-semibold text-primary">{ext(f.name)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium" title={f.name}>{f.name}</span>
                  <span className="block text-xs text-muted-foreground">{f.change === "created" ? "Made in this task" : "Changed"} · {formatBytes(f.size)}</span>
                </span>
                <FileLink chatId={chatId} name={f.name} download title="Download"
                          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
                  <Download className="h-4 w-4" />
                </FileLink>
              </div>
            ))}
            {read.length > 0 && (details
              ? read.map((n) => <p key={n} className="truncate font-mono text-[11px] text-muted-foreground" title={n}>read {n}</p>)
              : <p className="text-xs text-muted-foreground">Read {read.length === 1 ? read[0] : `${read.length} files`}.</p>)}
          </div>
        </Section>
      )}

      {web.length > 0 && (
        <Section title="Sources">
          <ol className="space-y-2">
            {web.map((s, i) => (
              <li key={s.url} className="flex gap-2 text-sm">
                <span className="w-5 shrink-0 font-mono text-[11px] text-muted-foreground">[{i + 1}]</span>
                <a href={s.url} target="_blank" rel="noreferrer noopener" className="group min-w-0 hover:underline">
                  <span className="line-clamp-2">{s.title}</span>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">{s.site}<ExternalLink className="h-3 w-3 opacity-0 group-hover:opacity-100" /></span>
                </a>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {details && showStats && stats && (stats.completion_tokens ?? 0) > 0 && (
        <Section title="This run">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {stats.model && <span className="rounded-sm bg-muted px-1.5 py-0.5 font-medium">{stats.model}</span>}
            <Stats stats={stats} />
          </div>
        </Section>
      )}
    </aside>
  )
}
