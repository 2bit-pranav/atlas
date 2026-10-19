/**
 * One turn = a user message and the assistant's answer, after llama.cpp's
 * `ChatMessageUser` / `ChatMessageAssistant`.
 *
 * Every row is memoised on its turn object. The store replaces only the turn
 * that changed, so while one answer streams, no other row renders at all --
 * and switching versions with `<` `>` re-renders the rows that switched.
 */

import { memo, useEffect, useRef, useState } from "react"
import {
  BookOpenText, Check, ChevronDown, ChevronLeft, ChevronRight, Clock, Copy, Download, Eye, Gauge,
  Lightbulb, Pencil, Quote, RefreshCw, ShieldAlert, Sparkles, WholeWord, Wrench,
} from "lucide-react"

import { atlas, useAtlas } from "@/lib/store"
import { usePrefs } from "@/lib/prefs"
import { fileUrl } from "@/lib/api"
import type { ChangedFile, ChatFile, Part, Ref, Turn, TurnStats } from "@/lib/types"
import { answerText } from "@/lib/transcript"
import { cn } from "@/lib/utils"
import { Markdown } from "@/components/chat/Markdown"
import { Composer, formatBytes } from "@/components/chat/Composer"
import { ToolBlock } from "@/components/chat/ToolBlock"
import { Tip } from "@/components/ui/tip"

// ------------------------------------------------------------------ turn --

export const TurnRow = memo(function TurnRow({ turn, chatId, isLast, laterCount, liveParts, liveStats }: {
  turn: Turn
  chatId: string
  isLast: boolean
  /** How many turns come after this one: what an edit here would delete. */
  laterCount: number
  liveParts: Part[] | null
  liveStats: TurnStats | null
}) {
  const [editing, setEditing] = useState(false)
  const parts = liveParts ?? turn.render
  const running = turn.status === "running"
  return (
    <div className="w-full" data-turn-id={turn.id}>
      <UserMessage turn={turn} chatId={chatId} editing={editing} setEditing={setEditing} laterCount={laterCount} />
      <AssistantMessage turn={turn} chatId={chatId} parts={parts} stats={liveStats ?? turn.stats} running={running} isLast={isLast} />
    </div>
  )
})

// ------------------------------------------------------------------ user --

function UserMessage({ turn, chatId, editing, setEditing, laterCount }: {
  turn: Turn; chatId: string; editing: boolean; setEditing: (v: boolean) => void; laterCount: number
}) {
  const busy = useAtlas((s) => s.run !== null)

  if (editing) {
    return (
      <div className="mt-12 flex flex-col items-end">
        <div className="w-full max-w-[80%]">
          <Composer edit={{
            initialText: turn.user_text,
            initialFiles: turn.files,
            onSubmit: async (text, files) => {
              const ok = await atlas.edit(turn.id, text, files)
              if (ok) setEditing(false)
              return ok
            },
            onCancel: () => setEditing(false),
          }} />
          <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {laterCount > 0
                ? `Sending replaces this answer and deletes the ${laterCount} message${laterCount > 1 ? "s" : ""} after it.`
                : "Sending replaces this answer and its other versions."}
            </span>
            <button type="button" onClick={() => setEditing(false)} className="rounded-md px-3 py-1 hover:bg-accent">Cancel</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="mt-12 flex flex-col items-end gap-2">
      {turn.files.length > 0 && <Attachments files={turn.files} chatId={chatId} />}
      {turn.refs?.length > 0 && <RefChips refs={turn.refs} />}
      {turn.user_text && (
        <div className={cn("max-w-[80%] whitespace-pre-wrap break-words rounded-[1.125rem] bg-primary/5 px-3.5 text-[15px] leading-7 dark:bg-primary/15",
                           turn.user_text.includes("\n") ? "py-2.5" : "py-1.5")}>
          <WithMentions text={turn.user_text} />
        </div>
      )}
      <div className="flex h-6 items-center gap-2">
        <CopyButton text={turn.user_text} />
        <Action label="Edit" onClick={() => setEditing(true)} disabled={busy}><Pencil className="h-3 w-3" /></Action>
      </div>
    </div>
  )
}

const ASK_TITLE = {
  install: "Atlas wants to install something",
  access: "Atlas wants to use a folder outside its allowed ones",
  tool: "Atlas wants to use a tool that needs your approval",
} as const
const DONE_TITLE = { install: "Install request", access: "Folder access request", tool: "Tool approval" } as const

/**
 * The agent wants to do something that needs the user: install a package,
 * reach a folder outside the allowed ones, or call an MCP tool marked "ask".
 * Allow or Deny; no answer by the deadline counts as Deny (the backend
 * decides, this only shows the clock).
 */
function ApprovalCard({ part, live }: { part: Extract<Part, { kind: "approval" }>; live: boolean }) {
  const [now, setNow] = useState(() => Date.now())
  const [sent, setSent] = useState(false)
  const pending = part.status === "pending" && live
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [pending])
  const left = Math.max(0, Math.ceil((part.expires_at - now) / 1000))
  const outcome = {
    pending: live ? null : "Not answered",
    allowed: "Allowed",
    denied: "Declined: not run",
    expired: "No answer in time: not run",
  }[part.status]
  return (
    <div className={cn("my-3 rounded-xl border p-3.5",
                       pending ? "border-amber-500/50 bg-amber-500/5" : "bg-muted/30")}>
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShieldAlert className={cn("h-4 w-4", pending ? "text-amber-500" : "text-muted-foreground")} />
        {(pending ? ASK_TITLE : DONE_TITLE)[part.request ?? "install"]}
        {pending && <span className="ml-auto font-mono text-xs text-muted-foreground">{left}s</span>}
        {outcome && (
          <span className={cn("ml-auto text-xs", part.status === "allowed" ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
            {outcome}
          </span>
        )}
      </div>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-code p-2.5 font-mono text-xs text-code-foreground">{part.command}</pre>
      {pending && (
        <div className="mt-3 flex items-center gap-2">
          <button type="button" disabled={sent} onClick={() => { setSent(true); void atlas.answerApproval(part.id, true) }}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50">
            Allow
          </button>
          <button type="button" disabled={sent} onClick={() => { setSent(true); void atlas.answerApproval(part.id, false) }}
                  className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50">
            Deny
          </button>
          <span className="text-[11px] text-muted-foreground">
            {part.request === "access" && part.folder
              ? <>Allows {part.folder} for the rest of this answer. To allow it always, add it under Settings &gt; Access.</>
              : "Runs on this computer with your permissions."}
          </span>
        </div>
      )}
    </div>
  )
}

/** User text with each `@name` shown as a token, like the composer inserted it. */
function WithMentions({ text }: { text: string }) {
  const parts = text.split(/((?<![\w@])@(?:"[^"\n]+"|[\w.-]+))/g)
  return (
    <>
      {parts.map((p, i) => p.startsWith("@") && i % 2 === 1
        ? <span key={i} className="rounded bg-primary/10 px-1 font-mono text-[0.9em]">{p}</span>
        : p)}
    </>
  )
}

/** An answer given up on after a failure, before Atlas sent the model back to work. */
function Superseded({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="my-2">
      <button type="button" onClick={() => setOpen(!open)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
        <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        Earlier attempt, replaced after a tool failed and the model tried again
      </button>
      {open && <div className="mt-1 border-l pl-3 text-sm text-muted-foreground line-through decoration-muted-foreground/40"><Markdown text={text} /></div>}
    </div>
  )
}

/** Passages selected in the preview panel that went with this question. */
export function RefChips({ refs, onRemove }: { refs: Ref[]; onRemove?: (i: number) => void }) {
  return (
    <div className="flex max-w-[80%] flex-col items-end gap-1.5">
      {refs.map((r, i) => (
        <div key={i} className="group flex max-w-full items-start gap-2 rounded-lg border bg-muted/50 px-2.5 py-1.5 text-xs">
          <Quote className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="min-w-0">
            <span className="line-clamp-2 italic text-foreground/80">{r.quote}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{r.file}</span>
          </span>
          {onRemove && (
            <button type="button" onClick={() => onRemove(i)} aria-label="Remove passage"
                    className="text-muted-foreground hover:text-foreground">×</button>
          )}
        </div>
      ))}
    </div>
  )
}

/** Files this answer created or changed: open in the preview, or download. */
function ProducedFiles({ files, chatId }: { files: ChangedFile[]; chatId: string }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {files.map((f) => {
        const ext = f.name.includes(".") ? f.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
        return (
          <div key={f.name} className="flex items-center gap-3 rounded-lg border bg-muted p-2 pr-1.5">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">{ext}</span>
            <span className="min-w-0">
              <span className="block max-w-48 truncate text-sm font-medium" title={f.name}>{f.name}</span>
              <span className="block text-xs text-muted-foreground">{f.change === "created" ? "Created" : "Updated"} · {formatBytes(f.size)}</span>
            </span>
            <Tip label="Preview">
              <button type="button" onClick={() => atlas.openPreview(f.name)}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground">
                <Eye className="h-3.5 w-3.5" />
              </button>
            </Tip>
            <Tip label="Download">
              <a href={fileUrl(chatId, f.name, true)}
                 className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground">
                <Download className="h-3.5 w-3.5" />
              </a>
            </Tip>
          </div>
        )
      })}
    </div>
  )
}

function Attachments({ files, chatId }: { files: ChatFile[]; chatId: string }) {
  return (
    <div className="flex max-w-[80%] flex-wrap justify-end gap-2">
      {files.map((f) => {
        const image = f.type.startsWith("image/")
        const ext = f.name.includes(".") ? f.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
        return image ? (
          <button key={f.path} type="button" onClick={() => atlas.openPreview(f.name)}
                  className="overflow-hidden rounded-lg bg-muted shadow-lg">
            <img src={fileUrl(chatId, f.name)} alt={f.name} className="max-h-40" />
          </button>
        ) : (
          <button key={f.path} type="button" onClick={() => atlas.openPreview(f.name)} title="Open in the preview panel"
             className="flex items-center gap-3 rounded-lg border bg-muted p-2.5 text-left hover:bg-accent">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">{ext}</span>
            <span className="min-w-0">
              <span className="block max-w-40 truncate text-sm font-medium">{f.name}</span>
              <span className="block text-xs text-muted-foreground">{formatBytes(f.size)}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------- assistant --

function AssistantMessage({ turn, chatId, parts, stats, running, isLast }: {
  turn: Turn; chatId: string; parts: Part[]; stats: TurnStats | null; running: boolean; isLast: boolean
}) {
  const prefs = usePrefs()
  const busy = useAtlas((s) => s.run !== null)
  const currentModel = useAtlas((s) => String(s.settings?.values["model.name"] ?? ""))
  // The model that wrote this version, falling back to the current one for
  // turns recorded before models were stored.
  const modelName = stats?.model ?? currentModel
  const empty = parts.length === 0
  const lastIndex = parts.length - 1

  return (
    <div className="mt-6 w-full text-[15px] leading-[1.875rem]">
      {running && empty && <span className="shimmer-text text-sm">Processing...</span>}

      {parts.map((part, i) => {
        if (part.kind === "reasoning")
          return <Reasoning key={i} text={part.text} streaming={running && i === lastIndex}
                            interrupted={!running && turn.status !== "completed"} defaultOpen={prefs.expandReasoning} />
        if (part.kind === "tool")
          return <ToolBlock key={part.id || i} part={part} defaultOpen={prefs.expandTools} />
        if (part.kind === "approval")
          return <ApprovalCard key={part.id} part={part} live={running} />
        if (part.kind === "superseded")
          return <Superseded key={i} text={part.text} />
        return <Markdown key={i} text={part.text} />
      })}

      {!running && turn.status !== "completed" && (
        <p className={cn("mt-3 text-xs italic", turn.status === "failed" ? "text-destructive" : "text-muted-foreground")}>
          {turn.status === "cancelled" ? "Stopped." :
           turn.status === "interrupted" ? "Interrupted: the backend restarted during this answer." :
           turn.error ?? "This answer failed."}
          {isLast && " Regenerate or edit the question to continue."}
        </p>
      )}

      {!running && stats?.files && stats.files.length > 0 && <ProducedFiles files={stats.files} chatId={chatId} />}

      {!running && (
        <>
          {prefs.showStats && stats && (stats.completion_tokens ?? 0) > 0 && (
            <div className="my-4 inline-flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {modelName && <span className="rounded-sm bg-muted px-1.5 py-0.5 font-medium">{modelName}</span>}
              <Stats stats={stats} />
            </div>
          )}
          <div className="mt-2 flex h-6 items-center gap-2">
            {turn.versions.length > 1 && (
              <span className="flex items-center gap-0.5">
                <Action label="Previous version" disabled={busy || turn.version <= 0}
                        onClick={() => void atlas.selectVersion(turn.id, -1)}>
                  <ChevronLeft className="h-4 w-4" />
                </Action>
                <span className="font-mono text-xs tabular-nums text-muted-foreground">{turn.version + 1}/{turn.versions.length}</span>
                <Action label="Next version" disabled={busy || turn.version >= turn.versions.length - 1}
                        onClick={() => void atlas.selectVersion(turn.id, +1)}>
                  <ChevronRight className="h-4 w-4" />
                </Action>
              </span>
            )}
            <CopyButton text={answerText(parts)} />
            {isLast && (
              <Action label="Regenerate" disabled={busy} onClick={() => void atlas.retry(turn.id)}>
                <RefreshCw className="h-3 w-3" />
              </Action>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** Reasoning, after llama.cpp's `ChatMessageReasoningBlock`. */
const Reasoning = memo(function Reasoning({ text, streaming, interrupted, defaultOpen }: {
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

/** Generation and reading stats, after llama.cpp's `ChatMessageStatistics`. */
function Stats({ stats }: { stats: TurnStats }) {
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

function Action({ label, onClick, disabled, children }: {
  label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <Tip label={label}>
      <button type="button" onClick={onClick} disabled={disabled} aria-label={label}
              className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:opacity-30">
        {children}
      </button>
    </Tip>
  )
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <Action label={done ? "Copied" : "Copy"} onClick={() => {
      void navigator.clipboard.writeText(text)
      setDone(true)
      setTimeout(() => setDone(false), 1200)
    }}>
      {done ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
    </Action>
  )
}
