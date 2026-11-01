/** The panel's chat history: browser chats only. */

import { useState } from "react"
import { ArrowLeft, Search, Trash2 } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import type { ChatSummary } from "@/api/types"
import { fullTime, timeAgo, useNow } from "@/lib/time"
import { host } from "../url"

/** The chats started in the browser, newest first. The web UI keeps all of them, grouped with the rest. */
export function HistoryView({ onOpen, onClose }: { onOpen: (c: ChatSummary) => void; onClose: () => void }) {
  const chats = useAtlas((s) => s.chats)
  const now = useNow()
  const [query, setQuery] = useState("")
  const [confirm, setConfirm] = useState<string | null>(null)
  const q = query.trim().toLowerCase()
  const list = chats
    .filter((c) => c.source === "extension")
    .filter((c) => !q || [c.title, c.page_title, c.page_url].some((t) => t?.toLowerCase().includes(q)))
    .sort((a, b) => b.updated_at - a.updated_at)
  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <button type="button" title="Back" onClick={onClose} className="rounded-md p-1.5 hover:bg-accent">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <span className="flex-1 text-sm font-medium">Browser chats</span>
      </header>
      <div className="border-b px-3 py-2">
        <label className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chats and pages"
                 className="min-w-0 flex-1 bg-transparent text-sm outline-none" autoFocus />
        </label>
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {list.length === 0 && (
          <li className="p-4 text-center text-xs text-muted-foreground">
            {q ? "No chat matches." : "No browser chats yet. Ask about a page to start one."}
          </li>
        )}
        {list.map((c) => (
          <li key={c.id} className="group flex items-start gap-1 rounded-lg hover:bg-accent">
            <button type="button" onClick={() => onOpen(c)} className="min-w-0 flex-1 px-2 py-1.5 text-left" title={c.page_url}>
              <p className="truncate text-sm">{c.title || "New chat"}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {host(c.page_url) || "no page"} · <span title={fullTime(c.updated_at)}>{timeAgo(c.updated_at, now)}</span>
              </p>
            </button>
            {confirm === c.id ? (
              <span className="flex shrink-0 items-center gap-1 py-1.5 pr-1 text-[11px]">
                <button type="button" className="rounded px-1.5 py-0.5 hover:bg-background" onClick={() => setConfirm(null)}>Keep</button>
                <button type="button" className="rounded bg-destructive px-1.5 py-0.5 text-destructive-foreground"
                        onClick={() => void atlas.deleteChat(c.id).then(() => setConfirm(null))}>Delete</button>
              </span>
            ) : (
              <button type="button" title="Delete" onClick={() => setConfirm(c.id)}
                      className="shrink-0 rounded p-1.5 text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
