import { useContext } from "react"
import { Pencil, Quote } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import { FileImage, FileLink } from "@/features/chat/FileLink"
import type { ChatFile, Part, Ref, Turn, TurnStats } from "@/api/types"
import { cn } from "@/lib/cn"
import { Composer } from "@/features/composer/Composer"
import { formatBytes } from "@/lib/format"
import { fullTime, timeAgo, useNow } from "@/lib/time"
import { Action, CopyButton } from "@/features/chat/MessageActions"
import { PanelLayout, TaskLayout } from "@/features/task/layout"
import { TaskStatus } from "@/features/task/TaskStatus"

// ------------------------------------------------------------------ user --

export function UserMessage({ turn, chatId, editing, setEditing, laterCount, parts, stats }: {
  turn: Turn; chatId: string; editing: boolean; setEditing: (v: boolean) => void; laterCount: number
  parts: Part[]; stats: TurnStats | null
}) {
  const busy = useAtlas((s) => s.run !== null || s.pending !== null)
  const task = useContext(TaskLayout)
  const panel = useContext(PanelLayout)

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

  if (panel) {
    // The side panel: a compact bubble; copy and edit on hover, no time.
    return (
      <div className="group/request mt-5 flex flex-col items-end gap-1 first:mt-1">
        {turn.files.length > 0 && <Attachments files={turn.files} chatId={chatId} />}
        {turn.user_text && (
          <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-[14px] rounded-br-[4px] bg-muted px-3 py-1.5 text-[13.5px] leading-relaxed">
            <WithMentions text={turn.user_text} />
          </div>
        )}
        <div className="flex h-5 items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover/request:opacity-100">
          <CopyButton text={turn.user_text} />
          <Action label="Edit" onClick={() => setEditing(true)} disabled={busy}><Pencil className="h-3 w-3" /></Action>
        </div>
      </div>
    )
  }

  if (task) {
    // The task view: the request as plain text under its state, not a bubble.
    return (
      <div className="group/request mt-12 grid gap-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <TaskStatus turn={turn} parts={parts} stats={stats} />
          <span>You asked, <SentAt at={turn.created_at} /></span>
          <span className="ml-auto flex items-center gap-1 transition-opacity focus-within:opacity-100 md:opacity-0 md:group-hover/request:opacity-100">
            <CopyButton text={turn.user_text} />
            <Action label="Edit" onClick={() => setEditing(true)} disabled={busy}><Pencil className="h-3 w-3" /></Action>
          </span>
        </div>
        {turn.files.length > 0 && <Attachments files={turn.files} chatId={chatId} align="start" />}
        {turn.refs?.length > 0 && <RefChips refs={turn.refs} />}
        {turn.user_text && (
          <p className="whitespace-pre-wrap break-words text-base leading-relaxed"><WithMentions text={turn.user_text} /></p>
        )}
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
        <SentAt at={turn.created_at} />
        <CopyButton text={turn.user_text} />
        <Action label="Edit" onClick={() => setEditing(true)} disabled={busy}><Pencil className="h-3 w-3" /></Action>
      </div>
    </div>
  )
}

/** "2 min ago" under a user message; the exact time on hover. */
function SentAt({ at }: { at: number }) {
  const now = useNow()
  return <span className="text-xs text-muted-foreground" title={fullTime(at)}>{timeAgo(at, now)}</span>
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

/** Passages that went with this question (selected in the former preview panel; older chats only). */
function RefChips({ refs }: { refs: Ref[] }) {
  return (
    <div className="flex max-w-[80%] flex-col items-end gap-1.5">
      {refs.map((r, i) => (
        <div key={i} className="group flex max-w-full items-start gap-2 rounded-lg border bg-muted/50 px-2.5 py-1.5 text-xs">
          <Quote className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="min-w-0">
            <span className="line-clamp-2 italic text-foreground/80">{r.quote}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{r.file}</span>
          </span>
        </div>
      ))}
    </div>
  )
}

function Attachments({ files, chatId, align = "end" }: { files: ChatFile[]; chatId: string; align?: "start" | "end" }) {
  return (
    <div className={cn("flex max-w-[80%] flex-wrap gap-2", align === "end" ? "justify-end" : "justify-start")}>
      {files.map((f) => {
        const image = f.type.startsWith("image/")
        const ext = f.name.includes(".") ? f.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
        return image ? (
          <FileLink key={f.path} chatId={chatId} name={f.name} className="overflow-hidden rounded-lg bg-muted shadow-lg">
            <FileImage chatId={chatId} name={f.name} className="max-h-40" />
          </FileLink>
        ) : (
          <FileLink key={f.path} chatId={chatId} name={f.name} download title="Download"
             className="flex items-center gap-3 rounded-lg border bg-muted p-2.5 text-left hover:bg-accent">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">{ext}</span>
            <span className="min-w-0">
              <span className="block max-w-40 truncate text-sm font-medium">{f.name}</span>
              <span className="block text-xs text-muted-foreground">{formatBytes(f.size)}</span>
            </span>
          </FileLink>
        )
      })}
    </div>
  )
}
