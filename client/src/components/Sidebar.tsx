/**
 * The sidebar, after llama.cpp's `SidebarNavigation`: a floating rounded
 * panel that collapses to an icon rail, an action list with shortcut hints on
 * hover, and the conversation list with a "more actions" menu per row.
 */

import { memo, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import * as Dropdown from "@radix-ui/react-dropdown-menu"
import {
  Download, Loader2, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Pencil, Plug, RotateCw, Search,
  Settings, Sparkles, SquarePen, Trash2, X,
} from "lucide-react"

import { atlas, useAtlas } from "@/lib/store"
import { shortcutKeys, type ShortcutAction } from "@/lib/shortcuts"
import { downloadJson, exportName } from "@/lib/download"
import type { ChatSummary } from "@/lib/types"
import { cn } from "@/lib/utils"
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
  const [query, setQuery] = useState("")
  const restarting = useAtlas((s) => s.restarting)
  const pendingRestart = useAtlas((s) => Object.keys(s.settings?.pending_restart ?? {}).length > 0)
  const answering = useAtlas((s) => s.run !== null)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? chats.filter((c) => (c.title || "New chat").toLowerCase().includes(q)) : chats
  }, [chats, query])

  const actions: {
    icon: typeof Search; label: string; action?: ShortcutAction; run: () => void; path?: string
    /** A dot: something is waiting on this action. */
    dot?: boolean; busy?: boolean; disabled?: boolean; hint?: string
  }[] = [
    { icon: SquarePen, label: "New chat", action: "newChat", run: () => { atlas.newChat(); navigate("/") } },
    { icon: Search, label: "Search", action: "search", run: () => { if (!open) onToggle(); setSearching(true) } },
    { icon: Sparkles, label: "Skills", path: "/skills", run: () => navigate("/skills") },
    { icon: Plug, label: "MCP", path: "/mcp", run: () => navigate("/mcp") },
    { icon: Settings, label: "Settings", action: "settings", path: "/settings", run: () => navigate("/settings") },
    { icon: RotateCw, label: restarting ? "Restarting..." : "Restart", run: () => void atlas.restart(),
      dot: pendingRestart, busy: restarting, disabled: restarting || answering,
      hint: answering ? "Wait for the answer to finish"
        : pendingRestart ? "Saved settings (such as the model) take effect after a restart"
        : "Restart llama-server and the backend" },
  ]

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-20 bg-background/60 backdrop-blur-sm md:hidden" onClick={onToggle} />
      )}
      <aside
        className={cn(
          "z-30 flex flex-col pt-2 transition-[width,padding] duration-200 ease-out",
          "fixed left-2 top-2 h-[calc(100dvh-1rem)] rounded-3xl md:sticky md:ml-2 md:mt-2 md:h-[calc(100dvh-1.125rem)] md:rounded-2xl",
          open ? "w-[calc(100dvw-1rem)] bg-muted/95 shadow-md backdrop-blur-xl md:w-72 md:bg-muted/60"
               : "hidden w-12 md:flex",
        )}
      >
        <div className={cn("flex items-center px-2", open ? "justify-between" : "justify-center")}>
          {open ? (
            <button type="button" onClick={() => { atlas.newChat(); navigate("/") }}
                    className="rounded-full px-2.5 py-1.5 text-[15px] font-semibold tracking-tight hover:bg-foreground/5">
              Atlas
            </button>
          ) : (
            <Tip label="Open sidebar" side="right">
              <button type="button" onClick={onToggle} className="flex h-9 w-9 items-center justify-center rounded-full hover:bg-accent">
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            </Tip>
          )}
          {open && (
            <Tip label="Close sidebar" side="bottom">
              <button type="button" onClick={onToggle} className="flex h-9 w-9 items-center justify-center rounded-full hover:bg-accent">
                <PanelLeftClose className="hidden h-4 w-4 md:block" />
                <X className="h-4 w-4 md:hidden" />
              </button>
            </Tip>
          )}
        </div>

        <div className={cn("mt-3 space-y-0.5", open ? "px-2" : "flex flex-col items-center")}>
          {open && searching ? (
            <SearchBox value={query} onChange={setQuery} onClose={() => { setQuery(""); setSearching(false) }} />
          ) : actions.map((a) => {
            const active = a.path && location.pathname.startsWith(a.path)
            return open ? (
              <button key={a.label} type="button" onClick={a.run} disabled={a.disabled} title={a.hint}
                      className={cn("group flex h-9 w-full items-center justify-between rounded-lg px-2 text-sm transition-colors hover:bg-foreground/10 disabled:opacity-60 disabled:hover:bg-transparent",
                                    active && "bg-accent text-accent-foreground")}>
                <span className="flex items-center gap-2.5">
                  <a.icon className={cn("h-4 w-4", a.busy && "animate-spin")} />{a.label}
                  {a.dot && !a.busy && <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />}
                </span>
                {a.action && (
                  <kbd className="font-sans text-[11px] font-medium text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                    {shortcutKeys(a.action).join(" ")}
                  </kbd>
                )}
              </button>
            ) : (
              <Tip key={a.label} label={a.hint ?? a.label} side="right">
                <button type="button" onClick={a.run} disabled={a.disabled}
                        className={cn("relative flex h-9 w-9 items-center justify-center rounded-full hover:bg-accent disabled:opacity-60", active && "bg-accent")}>
                  <a.icon className={cn("h-4 w-4", a.busy && "animate-spin")} />
                  {a.dot && !a.busy && <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-amber-500" />}
                </button>
              </Tip>
            )
          })}
        </div>

        {open && (
          <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            <p className="flex h-8 items-center px-2 text-xs font-medium text-muted-foreground">
              {query ? "Search results" : "Recent conversations"}
            </p>
            {visible.length === 0 ? (
              <p className="px-2 py-1 text-xs text-muted-foreground">{query ? "No results found" : "No conversations yet"}</p>
            ) : (
              <ul className="space-y-0.5">
                {visible.map((chat) => (
                  <ChatItem
                    key={chat.id}
                    chat={chat}
                    active={chat.id === activeId && location.pathname.startsWith("/c/")}
                    running={chat.id === runningChat}
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
        placeholder="Search conversations..."
        className="h-9 w-full rounded-lg border border-border/30 bg-background/70 pl-8 pr-8 text-sm outline-none focus:border-border"
      />
      <button type="button" onClick={onClose} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label="Close search">
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

const ChatItem = memo(function ChatItem({ chat, active, running, renaming, onOpen, onRename, onRenamed, onDelete }: {
  chat: ChatSummary
  active: boolean
  running: boolean
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
        className={cn("group flex min-h-9 w-full cursor-pointer items-center justify-between gap-1 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-foreground/10",
                      active && "bg-foreground/5 text-accent-foreground")}
      >
        <span className="flex min-w-0 items-center gap-2">
          {running && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />}
          <span className="truncate text-sm font-medium">{chat.title || "New chat"}</span>
        </span>
        <Dropdown.Root>
          <Dropdown.Trigger asChild>
            <button type="button" onClick={(e) => e.stopPropagation()} aria-label="More actions"
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md opacity-100 hover:bg-foreground/10 focus:opacity-100 data-[state=open]:opacity-100 md:opacity-0 md:group-hover:opacity-100">
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
