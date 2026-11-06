/**
 * The task rail: the brand, New task, the app's pages, the task list (a status
 * dot and when each was last touched, a "more actions" menu on hover) and what
 * Atlas runs on. Collapses to an icon rail; on phones it slides over the page.
 */

import { memo, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import * as Dropdown from "@radix-ui/react-dropdown-menu"
import {
  Download, Globe, PanelRight, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Pencil, Plug, Search,
  Settings, Sparkles, SquarePen, Trash2, X,
} from "lucide-react"

import { atlas, useAtlas } from "@/state/store"
import { shortcutKeys, type ShortcutAction } from "@/lib/shortcuts"
import { shortAgo, useNow } from "@/lib/time"
import { downloadJson, exportName } from "@/lib/download"
import type { ChatSummary } from "@/api/types"
import { cn } from "@/lib/cn"
import { Tip } from "@/components/ui/tip"

interface Props {
  open: boolean
  onToggle: () => void
  searching: boolean
  setSearching: (v: boolean) => void
  renaming: string | null
  setRenaming: (id: string | null) => void
  onDelete: (chat: ChatSummary) => void
}

export function Sidebar({ open, onToggle, searching, setSearching, renaming, setRenaming, onDelete }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const chats = useAtlas((s) => s.chats)
  const activeId = useAtlas((s) => s.chat?.id ?? s.stagedChat)
  const runningChat = useAtlas((s) => s.run?.chat_id ?? null)
  const waiting = useAtlas((s) => Boolean(s.live?.parts.some((p) => p.kind === "approval" && p.status === "pending")))
  const modelName = useAtlas((s) => String(s.settings?.values["model.name"] ?? ""))
  const now = useNow()
  const [query, setQuery] = useState("")

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? chats.filter((c) => (c.title || "New task").toLowerCase().includes(q)) : chats
  }, [chats, query])

  const actions: { icon: typeof Search; label: string; action?: ShortcutAction; run: () => void; path?: string }[] = [
    { icon: Search, label: "Search", action: "search", run: () => { if (!open) onToggle(); setSearching(true) } },
    { icon: Sparkles, label: "Skills", path: "/skills", run: () => navigate("/skills") },
    { icon: Plug, label: "MCP", path: "/mcp", run: () => navigate("/mcp") },
    { icon: PanelRight, label: "Browser extension", path: "/extension", run: () => navigate("/extension") },
    { icon: Settings, label: "Settings", action: "settings", path: "/settings", run: () => navigate("/settings") },
  ]

  const newTask = () => { atlas.newChat(); navigate("/") }

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-20 bg-background/60 backdrop-blur-sm md:hidden" onClick={onToggle} />
      )}
      <aside
        className={cn(
          "z-30 flex flex-col border-r bg-sidebar transition-[width] duration-200 ease-out",
          "fixed inset-y-0 left-0 h-dvh md:sticky md:top-0",
          open ? "w-[min(85vw,18rem)] shadow-lg md:w-62 md:shadow-none" : "hidden w-12 md:flex",
        )}
      >
        <div className={cn("flex h-13 shrink-0 items-center gap-2.5", open ? "px-4" : "justify-center")}>
          {open ? (
            <>
              <button type="button" onClick={newTask} className="flex items-center gap-2.5" aria-label="Atlas, new task">
                <span className="flex h-6.5 w-6.5 items-center justify-center rounded-lg bg-primary font-display text-[13px] font-semibold text-primary-foreground">A</span>
                <span className="font-display text-[15px] font-semibold tracking-tight">Atlas</span>
              </button>
              <span className="ml-auto font-mono text-xs text-muted-foreground">local</span>
              <Tip label="Close sidebar" side="bottom">
                <button type="button" onClick={onToggle} className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground">
                  <PanelLeftClose className="hidden h-4 w-4 md:block" />
                  <X className="h-4 w-4 md:hidden" />
                </button>
              </Tip>
            </>
          ) : (
            <Tip label="Open sidebar" side="right">
              <button type="button" onClick={onToggle} className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-accent">
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            </Tip>
          )}
        </div>

        {open ? (
          <button type="button" onClick={newTask}
                  className="mx-3 mb-2.5 mt-1 flex items-center gap-2 rounded-lg border bg-card px-2.5 py-2 text-sm font-medium shadow-sm transition-colors hover:bg-accent">
            <SquarePen className="h-4 w-4" />New task
            <kbd className="ml-auto font-mono text-[11px] font-normal text-muted-foreground">{shortcutKeys("newChat").join(" ")}</kbd>
          </button>
        ) : (
          <div className="flex flex-col items-center">
            <Tip label="New task" side="right">
              <button type="button" onClick={newTask} className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-accent">
                <SquarePen className="h-4 w-4" />
              </button>
            </Tip>
          </div>
        )}

        <div className={cn("space-y-0.5", open ? "px-2" : "flex flex-col items-center")}>
          {open && searching ? (
            <SearchBox value={query} onChange={setQuery} onClose={() => { setQuery(""); setSearching(false) }} />
          ) : actions.map((a) => {
            const active = a.path && location.pathname.startsWith(a.path)
            return open ? (
              <button key={a.label} type="button" onClick={a.run}
                      className={cn("group flex h-8.5 w-full items-center justify-between rounded-lg px-2 text-sm transition-colors hover:bg-accent",
                                    active && "bg-accent font-medium")}>
                <span className="flex items-center gap-2.5"><a.icon className="h-4 w-4 text-muted-foreground" />{a.label}</span>
                {a.action && (
                  <kbd className="font-mono text-[11px] font-normal text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                    {shortcutKeys(a.action).join(" ")}
                  </kbd>
                )}
              </button>
            ) : (
              <Tip key={a.label} label={a.label} side="right">
                <button type="button" onClick={a.run}
                        className={cn("flex h-9 w-9 items-center justify-center rounded-lg hover:bg-accent", active && "bg-accent")}>
                  <a.icon className="h-4 w-4" />
                </button>
              </Tip>
            )
          })}
        </div>

        {open && (
          <div className="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            <p className="flex h-8 items-center px-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {query ? "Search results" : "Tasks"}
            </p>
            {visible.length === 0 ? (
              <p className="px-2 py-1 text-xs text-muted-foreground">{query ? "No results found" : "No tasks yet"}</p>
            ) : (
              <ul className="space-y-0.5">
                {visible.map((chat) => (
                  <ChatItem
                    key={chat.id}
                    chat={chat}
                    active={chat.id === activeId && location.pathname.startsWith("/c/")}
                    status={chat.id === runningChat ? (waiting ? "ask" : "run") : DOT[chat.last_status ?? ""] ?? null}
                    when={shortAgo(chat.updated_at, now)}
                    renaming={renaming === chat.id}
                    onOpen={() => {
                      navigate(`/c/${chat.id}`)
                      if (window.innerWidth < 768) onToggle()
                    }}
                    onRename={() => setRenaming(chat.id)}
                    onRenamed={async (title) => {
                      setRenaming(null)
                      if (title && title !== chat.title) await atlas.renameChat(chat.id, title)
                    }}
                    onDelete={() => onDelete(chat)}
                  />
                ))}
              </ul>
            )}
          </div>
        )}
        {!open && <div className="flex-1" />}

        {open && (
          <div className="shrink-0 space-y-1 border-t px-4 py-3 text-xs text-muted-foreground">
            <p>Running on this computer</p>
            {modelName && (
              <p className="flex justify-between gap-2">
                <span>Model</span><span className="truncate font-medium text-foreground" title={modelName}>{modelName}</span>
              </p>
            )}
          </div>
        )}
      </aside>
    </>
  )
}

function SearchBox({ value, onChange, onClose }: { value: string; onChange: (v: string) => void; onClose: () => void }) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <input
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
        placeholder="Search tasks..."
        className="h-9 w-full rounded-lg border border-border/30 bg-background/70 pl-8 pr-8 text-sm outline-none focus:border-border"
      />
      <button type="button" onClick={onClose} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label="Close search">
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

/** A task's dot: working, needs you, done, failed or stopped (no dot before its first answer). */
const DOT: Record<string, "ok" | "bad" | "idle"> = { completed: "ok", failed: "bad", interrupted: "bad", cancelled: "idle" }
const DOT_CLASS = {
  run: "bg-run ring-[3px] ring-run/15 animate-pulse", ask: "bg-ask ring-[3px] ring-ask/15", ok: "bg-ok", bad: "bg-destructive",
  idle: "bg-muted-foreground/40",
} as const
const DOT_LABEL = { run: "Working", ask: "Needs you", ok: "Done", bad: "Failed", idle: "Stopped" } as const

const ChatItem = memo(function ChatItem({ chat, active, status, when, renaming, onOpen, onRename, onRenamed, onDelete }: {
  chat: ChatSummary
  active: boolean
  status: keyof typeof DOT_CLASS | null
  when: string
  renaming: boolean
  onOpen: () => void
  onRename: () => void
  onRenamed: (title: string) => void
  onDelete: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (renaming) input.current?.select()
  }, [renaming])

  if (renaming) {
    return (
      <li>
        <input
          ref={input}
          defaultValue={chat.title}
          onBlur={(e) => onRenamed(e.target.value.trim())}
          onKeyDown={(e) => {
            if (e.key === "Enter") onRenamed(e.currentTarget.value.trim())
            if (e.key === "Escape") onRenamed(chat.title)
          }}
          className="h-9 w-full rounded-lg border bg-background px-2 text-sm outline-none"
        />
      </li>
    )
  }

  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => e.key === "Enter" && onOpen()}
        className={cn("group flex min-h-8.5 w-full cursor-pointer items-center justify-between gap-1 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-accent",
                      active && "bg-accent text-accent-foreground")}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span title={status ? DOT_LABEL[status] : undefined} aria-label={status ? DOT_LABEL[status] : undefined}
                className={cn("h-2 w-2 shrink-0 rounded-full", status ? DOT_CLASS[status] : "bg-transparent")} />
          <span className="flex min-w-0 items-center gap-1.5 text-sm" title={chat.page_url || undefined}>
            {chat.source === "extension" && <Globe className="h-3 w-3 shrink-0 text-muted-foreground" />}
            <span className="truncate">{chat.title || "New task"}</span>
          </span>
        </span>
        <span className="hidden shrink-0 text-xs text-muted-foreground md:block md:group-hover:hidden md:group-focus-within:hidden">{when}</span>
        <Dropdown.Root>
          <Dropdown.Trigger asChild>
            <button type="button" onClick={(e) => e.stopPropagation()} aria-label="More actions"
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md hover:bg-foreground/10 data-[state=open]:flex md:hidden md:group-hover:flex md:group-focus-within:flex">
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content align="end" sideOffset={4} onClick={(e) => e.stopPropagation()}
                              className="z-50 min-w-44 rounded-lg border bg-popover p-1 text-sm text-popover-foreground shadow-md">
              <MenuItem icon={Pencil} label="Rename" keys={shortcutKeys("renameChat")} onSelect={onRename} />
              <MenuItem icon={Download} label="Export" keys={shortcutKeys("exportChat")} onSelect={async () => {
                downloadJson(exportName(chat.id, chat.title), (await atlas.exportChats([chat.id]))[0])
              }} />
              <Dropdown.Separator className="my-1 h-px bg-border" />
              <MenuItem icon={Trash2} label="Delete" keys={shortcutKeys("deleteChat")} onSelect={onDelete} destructive />
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      </div>
    </li>
  )
})

function MenuItem({ icon: Icon, label, keys, onSelect, destructive }: {
  icon: typeof Pencil; label: string; keys: string[]; onSelect: () => void; destructive?: boolean
}) {
  return (
    <Dropdown.Item onSelect={onSelect}
                   className={cn("flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-accent",
                                 destructive && "text-destructive")}>
      <Icon className="h-4 w-4" />
      <span className="flex-1">{label}</span>
      <span className="text-[11px] text-muted-foreground">{keys.join(" ")}</span>
    </Dropdown.Item>
  )
}
