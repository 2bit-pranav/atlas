import { useCallback, useEffect, useState } from "react"
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom"
import { AlertTriangle, Loader2, PanelLeftOpen, X } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import { matchShortcut } from "@/lib/shortcuts"
import { downloadJson, exportName } from "@/lib/download"
import type { ChatSummary } from "@/api/types"
import { Sidebar } from "@/app/Sidebar"
import { SettingsPage } from "@/features/settings/SettingsPage"
import { SkillsPage } from "@/features/skills/SkillsPage"
import { McpPage } from "@/features/mcp/McpPage"
import { ExtensionPage } from "@/features/extension-page/ExtensionPage"
import { ChatRoute } from "@/app/ChatRoute"
import { DeleteDialog } from "@/app/DeleteChatDialog"

const SIDEBAR_KEY = "atlas-sidebar-open"

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [sidebar, setSidebar] = useState(() => {
    try {
      return window.innerWidth >= 768 && localStorage.getItem(SIDEBAR_KEY) !== "false"
    } catch {
      return window.innerWidth >= 768
    }
  })
  const [searching, setSearching] = useState(false)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<ChatSummary | null>(null)
  const error = useAtlas((s) => s.error)
  const restarting = useAtlas((s) => s.restarting)
  const model = useAtlas((s) => String(s.settings?.values["model.name"] ?? ""))
  const title = useAtlas((s) => s.chat?.title)

  useEffect(() => {
    void atlas.init()
  }, [])

  useEffect(() => {
    document.title = title ? `${title} - Atlas` : "Atlas"
  }, [title])

  const toggleSidebar = useCallback(() => {
    setSidebar((open) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, String(!open))
      } catch {
        /* not remembered, still toggled */
      }
      return !open
    })
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = matchShortcut(e)
      if (!action) return
      e.preventDefault()
      const { chat, chats } = atlas.state
      const current = chats.find((c) => c.id === chat?.id)
      const index = chats.findIndex((c) => c.id === chat?.id)
      switch (action) {
        case "newChat":
          atlas.newChat()
          navigate("/")
          break
        case "search":
          setSidebar(true)
          setSearching(true)
          break
        case "toggleSidebar":
          toggleSidebar()
          break
        case "settings":
          navigate("/settings")
          break
        case "renameChat":
          if (current) {
            setSidebar(true)
            setSearching(false)
            setRenaming(current.id)
          }
          break
        case "deleteChat":
          if (current) setDeleting(current)
          break
        case "exportChat":
          if (current)
            void atlas.exportChats([current.id]).then(([data]) => downloadJson(exportName(current.id, current.title), data))
          break
        case "prevChat":
        case "nextChat": {
          const next = chats[action === "prevChat" ? Math.max(0, index - 1) : Math.min(chats.length - 1, index + 1)]
          if (next) navigate(`/c/${next.id}`)
          break
        }
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [navigate, toggleSidebar])

  const onChatPage = location.pathname === "/" || location.pathname.startsWith("/c/")

  return (
    <div className="flex h-dvh flex-col overflow-hidden md:flex-row">
      <Sidebar
        open={sidebar}
        onToggle={toggleSidebar}
        searching={searching}
        setSearching={setSearching}
        renaming={renaming}
        setRenaming={setRenaming}
        onDelete={setDeleting}
      />

      <main className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        {!sidebar && (
          <button type="button" onClick={toggleSidebar} aria-label="Open sidebar"
                  className="absolute left-3 top-3 z-10 flex h-9 w-9 items-center justify-center rounded-full hover:bg-accent md:hidden">
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}

        {restarting && (
          <div className="mx-auto mt-3 flex w-full max-w-3xl items-center gap-2 rounded-lg border bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
            Restarting with {model ? <span className="font-mono">{model}</span> : "the saved settings"}: loading the model.
            Chats are kept; send once this is gone.
          </div>
        )}

        {error && (
          <div className="mx-auto mt-3 flex w-full max-w-3xl items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{error}</span>
            <button type="button" onClick={atlas.clearError} aria-label="Dismiss"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        <div className={onChatPage ? "flex min-h-0 flex-1" : "hidden"}>
          <div className="min-w-0 flex-1">
            <Routes>
              <Route path="/" element={<ChatRoute />} />
              <Route path="/c/:chatId" element={<ChatRoute />} />
              <Route path="*" element={null} />
            </Routes>
          </div>
        </div>
        {!onChatPage && (
          <div className="min-h-0 flex-1">
            <Routes>
              <Route path="/settings" element={<Navigate to="/settings/general" replace />} />
              <Route path="/settings/:section" element={<SettingsPage />} />
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/mcp" element={<McpPage />} />
              <Route path="/extension" element={<ExtensionPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        )}
      </main>

      <DeleteDialog chat={deleting} onClose={() => setDeleting(null)} onConfirm={async (chat) => {
        setDeleting(null)
        await atlas.deleteChat(chat.id)
        if (location.pathname === `/c/${chat.id}`) navigate("/")
      }} />
    </div>
  )
}
