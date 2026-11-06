/**
 * The task's work, beside the conversation (wide screens): what needs the
 * user, the steps in plain words, the files made, the web pages used. Calm by
 * default; Details (a per-browser pref) adds the tool calls, every file read
 * and the run's stats.
 */

import { useMemo } from "react"
import { Check, Download, ExternalLink, Loader2, X } from "lucide-react"
import type { Part, Turn, TurnStats } from "@/api/types"
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

export function WorkPanel({ chatId, turn, parts, stats, running }: {
  chatId: string; turn: Turn; parts: Part[]; stats: TurnStats | null; running: boolean
}) {
  const { taskDetails: details, showStats } = usePrefs()
  const steps = useMemo(() => toSteps(parts, running), [parts, running])
  const shown = details ? steps : steps.filter((s) => !s.internal)
  const pending = running ? parts.filter((p): p is Extract<Part, { kind: "approval" }> => p.kind === "approval" && p.status === "pending") : []
  const read = useMemo(() => readFiles(parts), [parts])
  // A PDF read_pdf downloaded is an input, not something the task made.
  const made = (stats?.files ?? []).filter((f) => !read.includes(f.name))
  const web = useMemo(() => sources(parts), [parts])
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
        <span className={cn("mb-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", TONE[status.tone])}>
          {running && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}{status.label}
        </span>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">{running ? "Getting started…" : "Answered directly, without using any tools."}</p>
        ) : (
          <ol className="relative">
            {shown.map((s, i) => (
              <li key={s.key + i} className="relative flex gap-3 pb-3 last:pb-0">
                {i < shown.length - 1 && <span aria-hidden className="absolute left-2.5 top-6 -bottom-0.5 w-px bg-border" />}
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
        )}
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
