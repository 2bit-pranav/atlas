/**
 * The result of an action the user started from the panel (Fill): a small
 * card above the composer while it works and when it is done. It is not a
 * chat turn: nothing goes into the chat, and the user closes it.
 */

import { CircleAlert, CircleCheck, Loader2, X } from "lucide-react"
import { cn } from "@/lib/cn"
import type { FillNote } from "../actions/suggestFill"

export function ActionNote({ note, onClose }: { note: FillNote; onClose: () => void }) {
  const Icon = note.state === "working" ? Loader2 : note.state === "done" ? CircleCheck : CircleAlert
  return (
    <div role="status" aria-live="polite"
         className="mb-2 flex items-start gap-2.5 rounded-xl border bg-card px-3 py-2.5 shadow-sm">
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0",
                          note.state === "working" ? "animate-spin text-muted-foreground"
                            : note.state === "done" ? "text-ok" : "text-ask")} />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium leading-5">{note.title}</p>
        {note.lines?.map((line) => (
          <p key={line} className="mt-0.5 text-xs leading-[1.45] text-muted-foreground">{line}</p>
        ))}
      </div>
      {note.state !== "working" && (
        <button type="button" aria-label="Close" title="Close" onClick={onClose}
                className="-mr-1 -mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
