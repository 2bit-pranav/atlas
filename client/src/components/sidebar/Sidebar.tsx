import React, { useState } from "react"
import {
  MessageSquare,
  Plus,
  Search,
  PanelLeftClose,
  PanelLeft,
  Settings,
  Sun,
  Moon,
  Trash2,
  Cpu,
} from "lucide-react"
import { useTheme } from "@/context/ThemeContext"
import { useAtlas } from "@/services/atlasStore"
import type { ChatListItem } from "@/types/api"
import { cn } from "@/lib/utils"

interface SidebarProps {
  sessions: ChatListItem[]
  currentSessionId: string | null
  onSelectSession: (id: string) => void
  onNewChat: () => void
  onDeleteSession: (id: string) => void
  onOpenSettings: () => void
  isOpen: boolean
  onToggleOpen: () => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onOpenSettings,
  isOpen,
  onToggleOpen,
}) => {
  const { theme, setTheme, resolvedTheme } = useTheme()
  const { connected } = useAtlas()
  const [searchQuery, setSearchQuery] = useState("")
  const [showSearchInput, setShowSearchInput] = useState(false)

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const toggleTheme = () => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark")
  }

  if (!isOpen) {
    return (
      <div className="hidden md:flex flex-col items-center justify-between py-4 px-2.5 border-r border-border/80 bg-[hsl(var(--sidebar-bg))] w-14 shrink-0 transition-all select-none">
        <div className="flex flex-col items-center gap-4">
          <button
            onClick={onToggleOpen}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-foreground text-background shadow-xs hover:opacity-90 transition-opacity"
            title="Expand Sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <button
            onClick={onNewChat}
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-border/80 hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="New Chat"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col items-center gap-2">
          <button
            onClick={toggleTheme}
            className="flex h-9 w-9 items-center justify-center rounded-xl hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title={`Switch to ${resolvedTheme === "dark" ? "Light" : "Dark"} mode`}
          >
            {resolvedTheme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </button>
          <button
            onClick={onOpenSettings}
            className="flex h-9 w-9 items-center justify-center rounded-xl hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="Local Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <aside className="flex flex-col justify-between w-64 md:w-68 h-screen border-r border-border/80 bg-[hsl(var(--sidebar-bg))] transition-all select-none shrink-0 z-30">
      {/* Top Header */}
      <div className="p-3.5 flex flex-col gap-3">
        {/* Logo and controls */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground text-background shadow-xs">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-4 w-4"
              >
                <circle cx="12" cy="12" r="7" />
                <path d="M12 9v6" />
                <path d="M9 12h6" />
              </svg>
            </div>
            <span className="font-semibold text-sm tracking-tight text-foreground">
              Atlas
            </span>
          </div>

          <div className="flex items-center gap-1 text-muted-foreground">
            <button
              onClick={() => setShowSearchInput(!showSearchInput)}
              className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted/80 hover:text-foreground transition-colors"
              title="Search conversations"
            >
              <Search className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={onToggleOpen}
              className="flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted/80 hover:text-foreground transition-colors"
              title="Collapse sidebar"
            >
              <PanelLeftClose className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Optional Search bar */}
        {showSearchInput && (
          <div className="relative">
            <input
              type="text"
              placeholder="Search chats..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-2.5 py-1.5 text-xs rounded-lg bg-background border border-border/80 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              autoFocus
            />
          </div>
        )}

        {/* New Chat Button (Pill matching Screenshot 1) */}
        <button
          onClick={onNewChat}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-xl border border-border/80 bg-background/80 hover:bg-background text-xs font-medium text-foreground transition-all shadow-2xs hover:shadow-xs group"
        >
          <Plus className="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground" />
          <span>New Chat</span>
        </button>
      </div>

      {/* History List */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
        {filteredSessions.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground">
            No chats yet
          </div>
        ) : (
          filteredSessions.map((session) => {
            const isActive = session.id === currentSessionId
            return (
              <div
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={cn(
                  "group relative flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium cursor-pointer transition-colors",
                  isActive
                    ? "bg-muted text-foreground font-semibold"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                )}
              >
                <div className="flex items-center gap-2.5 truncate flex-1 pr-1">
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80" />
                  <span className="truncate">{session.title}</span>
                </div>

                {/* Delete button on hover */}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteSession(session.id)
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive rounded transition-opacity"
                  title="Delete chat"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            )
          })
        )}
      </div>

      {/* Bottom Area: Settings & Theme Toggle (Single User Local Only) */}
      <div className="p-3 border-t border-border/80 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          {/* Settings Trigger */}
          <button
            onClick={onOpenSettings}
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors"
          >
            <Settings className="h-3.5 w-3.5" />
            <span>Settings</span>
          </button>

          {/* Theme Toggle Button */}
          <button
            onClick={toggleTheme}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/70 transition-colors"
            title={`Switch to ${resolvedTheme === "dark" ? "Light" : "Dark"} mode`}
          >
            {resolvedTheme === "dark" ? (
              <Sun className="h-3.5 w-3.5 text-amber-400" />
            ) : (
              <Moon className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {/* Connection badge. The dot reflects what the backend last answered,
            not a hardcoded "offline" label, because a green dot next to the word
            Offline is a thing nobody believes after the first failure. */}
        <div className="flex items-center justify-between px-2.5 py-1 text-[10px] text-muted-foreground/80 bg-muted/40 rounded-md">
          <div className="flex items-center gap-1.5 truncate">
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full shrink-0",
                connected ? "bg-emerald-500" : "bg-destructive",
              )}
            />
            <span className="truncate">
              {connected ? "llama.cpp • connected" : "backend unreachable"}
            </span>
          </div>
          <span className="font-mono text-[9px] uppercase">local</span>
        </div>
      </div>
    </aside>
  )
}
