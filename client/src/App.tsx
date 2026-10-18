/**
 * The shell: sidebar, header, chat surface, settings.
 *
 * This file is now almost entirely layout. It owns no chat state and no
 * fetching -- that all lives in `atlasStore`, which is the only thing that
 * knows what the backend said. The component's job is to decide where things
 * go and to report which model is configured, because that is display state
 * with no other home.
 *
 * What was here before and is now gone: a mock engine that faked a five-step
 * planning workflow, a localStorage transcript that survived deletes, and a
 * model picker offering four model files that do not exist on this machine.
 * Every one of those looked like a feature and was a lie about the backend.
 */

import React, { useEffect, useState } from "react"
import { AlertTriangle, PanelLeft, SlidersHorizontal } from "lucide-react"

import { Sidebar } from "@/components/sidebar/Sidebar"
import { ChatSurface } from "@/components/chat/ChatSurface"
import { SettingsModal } from "@/components/settings/SettingsModal"
import { atlas, useAtlas } from "@/services/atlasStore"

export function App() {
  const state = useAtlas()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // Settings and the chat list, once, on mount.
  useEffect(() => {
    void atlas.init()
  }, [])

  // The real model, read from settings. Display only -- there is exactly one
  // and picking a different one is a settings.json edit, not a UI action.
  const modelPath = (state.settings?.values["model.path"] as string) ?? ""
  const modelName = modelPath ? modelPath.split(/[\\/]/).pop() : null

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground antialiased font-sans">
      <Sidebar
        sessions={state.chats}
        currentSessionId={state.chatId}
        onSelectSession={(id) => void atlas.openChat(id)}
        onNewChat={() => void atlas.newChat()}
        onDeleteSession={(id) => void atlas.deleteChat(id)}
        onOpenSettings={() => setSettingsOpen(true)}
        isOpen={sidebarOpen}
        onToggleOpen={() => setSidebarOpen((v) => !v)}
      />

      <main className="relative flex h-screen flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 select-none items-center justify-between border-b border-border/40 bg-background/50 px-4 backdrop-blur-xs">
          <div className="flex items-center gap-2">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                title="Open sidebar"
              >
                <PanelLeft className="h-4 w-4" />
              </button>
            )}
            <span className="max-w-[200px] truncate text-xs font-medium text-foreground sm:max-w-xs">
              {state.chats.find((c) => c.id === state.chatId)?.title || "Atlas"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            {modelName && (
              <div className="hidden items-center gap-1.5 rounded-full border border-border/50 bg-muted/50 px-2.5 py-1 font-mono text-[11px] text-muted-foreground sm:flex">
                <span className="max-w-[180px] truncate">{modelName}</span>
              </div>
            )}
            <button
              onClick={() => setSettingsOpen(true)}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              title="Settings"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </button>
          </div>
        </header>

        {/* Errors are shown once, at the top, from the backend's own message.
            An inline notification beats an alert dialog, and it does not hide
            the answer that was already on screen. */}
        {state.error && (
          <div className="flex items-start gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="whitespace-pre-wrap">{state.error}</span>
          </div>
        )}

        <div className="relative flex-1 overflow-hidden">
          <ChatSurface />
        </div>
      </main>

      <SettingsModal
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        settings={state.settings}
        onSave={(patch) => atlas.saveSettings(patch)}
        onRefresh={() => void atlas.refreshSettings()}
      />
    </div>
  )
}