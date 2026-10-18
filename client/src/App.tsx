/**
 * The shell: sidebar, routes, keyboard shortcuts, the delete dialog.
 *
 * Routes mirror llama.cpp's: the chat at `/` and `/c/:id`, and full pages for
 * Settings, Skills and MCP instead of modals. All chat state lives in
 * `lib/store`; this file only decides what is on screen.
 */

import { useCallback, useEffect, useState } from "react"
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom"
import * as Dialog from "@radix-ui/react-dialog"
import { AlertTriangle, PanelLeftOpen, X } from "lucide-react"

import { atlas, useAtlas } from "@/lib/store"
import { matchShortcut } from "@/lib/shortcuts"
import { downloadJson, exportName } from "@/lib/download"
import type { ChatSummary } from "@/lib/types"
import { Sidebar } from "@/components/Sidebar"
import { ChatScreen } from "@/components/chat/ChatScreen"
import { Button } from "@/components/ui/kit"
import { SettingsPage } from "@/pages/SettingsPage"
import { SkillsPage } from "@/pages/SkillsPage"
import { McpPage } from "@/pages/McpPage"

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

        {error && (
          <div className="mx-auto mt-3 flex w-full max-w-3xl items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{error}</span>
            <button type="button" onClick={atlas.clearError} aria-label="Dismiss"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        <div className={onChatPage ? "min-h-0 flex-1" : "hidden"}>
          <Routes>
            <Route path="/" element={<ChatRoute />} />
            <Route path="/c/:chatId" element={<ChatRoute />} />
            <Route path="*" element={null} />
          </Routes>
        </div>
        {!onChatPage && (
          <div className="min-h-0 flex-1">
            <Routes>
              <Route path="/settings" element={<Navigate to="/settings/general" replace />} />
              <Route path="/settings/:section" element={<SettingsPage />} />
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/mcp" element={<McpPage />} />
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

/** Keeps the URL and the open chat in step, in both directions. */
function ChatRoute() {
  const { chatId } = useParams()
  const navigate = useNavigate()
  const openId = useAtlas((s) => s.chat?.id ?? null)

  useEffect(() => {
    if (chatId) void atlas.openChat(chatId)
    else if (atlas.state.chat) atlas.newChat()
  }, [chatId])

  // A first message creates the chat: move the URL to it.
  useEffect(() => {
    if (!chatId && openId) navigate(`/c/${openId}`, { replace: true })
  }, [chatId, openId, navigate])

  return <ChatScreen />
}

function DeleteDialog({ chat, onClose, onConfirm }: {
  chat: ChatSummary | null
  onClose: () => void
  onConfirm: (chat: ChatSummary) => void
}) {
  return (
    <Dialog.Root open={chat !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-background p-5 shadow-lg">
          <Dialog.Title className="text-base font-semibold">Delete conversation</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-muted-foreground">
            "{chat?.title || "New chat"}" will be deleted, with every version, its model history and its uploaded files.
            This cannot be undone.
          </Dialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="destructive" onClick={() => chat && onConfirm(chat)} autoFocus>Delete</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
