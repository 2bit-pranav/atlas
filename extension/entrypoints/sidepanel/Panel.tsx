/**
 * The side panel: a chat with Atlas about the page in the current tab.
 *
 * The chat itself is the web UI's (`ChatScreen`, the shared store). What the
 * panel adds:
 *
 * - pairing with the backend: "Connect" opens Atlas's Browser extension page,
 *   which hands the token to the extension (the background worker keeps it);
 * - attaching the chat to one tab: each message carries that page as it is
 *   when sent (its snapshot: a Google file's text, an article, or the
 *   accessibility tree), so the model reads it without a tool call; the page
 *   tools and the store's client calls run in that tab. "Can read" on the
 *   page card turns this off;
 * - the chat is always about the tab in front: switch tabs and the next
 *   message is about that page (no banner asking). While an answer is being
 *   written it stays on the tab it started on, so its page operations never
 *   land on another page;
 * - under each answer, the page passages it quoted, highlighted (or marked
 *   as not on the page);
 * - questions from the selection chip and the right-click menu;
 * - a PDF tab (the browser's viewer runs no content script), or a PDF on a
 *   Google Drive file page, is sent as a file: before the chat's first message
 *   it is attached, and the pdf reader takes it (OCR included);
 * - looking: `page_screenshot` / `page_image` are answered here (capturing a
 *   tab and fetching images are extension powers), and the camera button
 *   attaches a screenshot to the next message;
 * - Fill: the form's fields go to Atlas, suggested values come back as a
 *   preview on the page, and are filled only on Apply. Never submitted;
 * - history: the browser's own chats, reopened from a list, and the last chat
 *   back when the panel opens again on its page.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Camera, ExternalLink, History, Plus, Settings } from "lucide-react"
import * as api from "@/api/client"
import { atlas, useAtlas } from "@/state/store"
import { AnswerExtras } from "@/state/slots"
import type { ChatSummary, Turn } from "@/api/types"
import { ChatScreen } from "@/features/chat/ChatScreen"
import { blocked, loadSettings, saveSettings, type ExtensionSettings } from "@ext/shared/settings"
import { activeTab, viewerUrl, type TabInfo } from "@ext/shared/tab"
import { dataUrlToFile, screenshot } from "@ext/shared/capture"
import { Status } from "./status"
import { isPdf, pdfName, savePdf } from "./actions/pdf"
import { usePendingAsks } from "./hooks/usePendingAsks"
import { sameUrl } from "./url"
import { QuoteSources } from "./components/QuoteSources"
import { Centered } from "./components/Centered"
import { SettingsView } from "./components/SettingsView"
import { HistoryView } from "./components/HistoryView"
import { PageCard } from "./components/PageCard"
import { PanelHome } from "./components/PanelHome"
import { bindPage } from "./actions/bindPage"
import { exportUrl, googleTarget } from "@ext/page/google"
import { suggestFill } from "./actions/suggestFill"

export function Panel() {
  const [settings, setSettings] = useState<ExtensionSettings | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [current, setCurrent] = useState<TabInfo | null>(null)
  const [attached, setAttached] = useState<TabInfo | null>(null)
  /** "Can read": each message carries the page. Off, messages are not about it. */
  const [reading, setReading] = useState(true)
  const chat = useAtlas((s) => s.chat)
  const error = useAtlas((s) => s.error)

  const connect = useCallback(async (s: ExtensionSettings) => {
    api.configureApi({ base: s.base, token: s.token })
    if (!s.token) return setStatus("unpaired")
    try {
      const response = await fetch(`${s.base.replace(/\/$/, "")}/api/health`, {
        headers: { Authorization: `Bearer ${s.token}` },
      })
      if (response.status === 401) return setStatus("unpaired")
      if (!response.ok) return setStatus("offline")
    } catch {
      return setStatus("offline")
    }
    await atlas.init()
    setStatus("ready")
  }, [])

  useEffect(() => {
    const load = () => void loadSettings().then((s) => {
      setSettings(s)
      void connect(s)
    })
    load()
    // Paired from Atlas's page while the panel is open: connect straight away.
    const changed = (changes: Record<string, unknown>) => {
      if ("settings" in changes) load()
    }
    browser.storage.onChanged.addListener(changed)
    return () => browser.storage.onChanged.removeListener(changed)
  }, [connect])

  // The current tab, kept up to date.
  useEffect(() => {
    const refresh = () => void activeTab().then(setCurrent)
    refresh()
    const onUpdated = (_id: number, info: { url?: string; title?: string; status?: string }) => {
      if (info.url || info.title || info.status === "complete") refresh()
    }
    browser.tabs.onActivated.addListener(refresh)
    browser.tabs.onUpdated.addListener(onUpdated)
    return () => {
      browser.tabs.onActivated.removeListener(refresh)
      browser.tabs.onUpdated.removeListener(onUpdated)
    }
  }, [])

  // The chat follows the tab in front, except while an answer is being written:
  // that run's page operations stay on the page it started on.
  const running = useAtlas((s) => s.run !== null)
  useEffect(() => {
    if (current && !running) setAttached(current)
  }, [current, running])

  const blockedReason = settings && attached ? blocked(attached.url, settings.neverRead) : null
  // A PDF in the browser's own viewer: sent as a file. In the Atlas viewer it is a readable page.
  const pdf = attached !== null && !attached.viewer && !blockedReason && isPdf(attached.url)
  // A file on Google Drive: downloaded with the user's session and attached, like a PDF tab.
  const drive = attached && !blockedReason ? googleTarget(attached.url) : null
  const driveId = drive?.app === "drive-file" ? drive.id : null

  // The store sends the attached page with each message and runs client calls there.
  // A PDF has no content script: it goes as a file instead, attached once per chat.
  const sentPdfs = useRef(new Set<string>())
  useEffect(() => {
    atlas.origin = attached && !blockedReason ? { url: attached.url, title: attached.title } : null
    bindPage(attached && !blockedReason && !pdf ? attached : null, reading)
    const named = (title: string) => `${title.replace(/\s+-\s+Google Drive$/i, "").replace(/\.pdf$/i, "") || "document"}.pdf`
    const file = !reading || !attached ? null
      : pdf ? { url: attached.url, name: pdfName(attached.url) }
      : driveId ? { url: exportUrl({ app: "drive-file", id: driveId }), name: named(attached.title) }
      : null
    atlas.beforeSend = file ? async () => {
      const chatId = atlas.state.chat?.id ?? atlas.state.stagedChat ?? ""
      if (sentPdfs.current.has(`${chatId}|${file.url}`)) return
      await atlas.attachSaved(file.name, (id) => savePdf(id, file.url, file.name))
      sentPdfs.current.add(`${atlas.state.chat?.id ?? atlas.state.stagedChat ?? ""}|${file.url}`)
    } : null
  }, [attached, blockedReason, pdf, reading, driveId])

  usePendingAsks(status === "ready", setAttached)

  // The last chat, remembered with its page, comes back when the panel opens there again.
  useEffect(() => {
    if (chat?.id && chat.turns.length && attached)
      void browser.storage.local.set({ lastChat: { id: chat.id, url: attached.url } })
  }, [chat?.id, chat?.turns.length, attached])
  const restored = useRef(false)
  useEffect(() => {
    if (status !== "ready" || !current || restored.current) return
    restored.current = true
    void browser.storage.local.get("lastChat").then(async ({ lastChat }) => {
      const last = lastChat as { id: string; url: string } | undefined
      if (last && sameUrl(last.url, current.url) && !atlas.state.chat) {
        await atlas.openChat(last.id)
        setAttached(current)
      }
    })
  }, [status, current])

  /** Reopen a past chat. It goes on about the tab in front, like every chat. */
  const openPast = async (summary: ChatSummary) => {
    setShowHistory(false)
    await atlas.openChat(summary.id)
    if (current) setAttached(current)
  }
  const [fillStatus, setFillStatus] = useState("")

  const extras = useMemo(() => (attached && !blockedReason && !pdf && reading
    ? (turn: Turn, answer: string) => <QuoteSources turn={turn} answer={answer} tabId={attached.id} />
    : null), [attached, blockedReason, pdf, reading])

  if (!settings || status === "loading") return <Centered>Connecting to Atlas…</Centered>
  if (showSettings || status === "unpaired" || status === "offline")
    return (
      <SettingsView
        settings={settings}
        status={status}
        onSave={async (patch) => {
          await saveSettings(patch) // the storage listener reconnects
          setShowSettings(false)
        }}
        onClose={status === "ready" ? () => setShowSettings(false) : undefined}
      />
    )

  const readable = Boolean(attached && !blockedReason && !pdf)
  const takeScreenshot = async () => {
    if (!attached) return
    const shot = await screenshot(attached.id)
    if ("error" in shot) return void atlas.fail(new Error(shot.error))
    await atlas.attach_files([dataUrlToFile(`data:image/jpeg;base64,${shot.data}`, "screenshot.jpg")])
  }

  if (showHistory) return <HistoryView onOpen={(c) => void openPast(c)} onClose={() => setShowHistory(false)} />

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex h-11 shrink-0 items-center gap-1.5 border-b pl-3 pr-1">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary font-display text-xs font-semibold text-primary-foreground">A</span>
        <span className="min-w-0 flex-1 truncate font-display text-[15px] font-semibold">{chat?.title || "Atlas"}</span>
        <HeaderButton label="Chats in the browser" onClick={() => {
          setShowHistory(true)
          void atlas.refreshChats()
        }}><History className="h-4 w-4" /></HeaderButton>
        <HeaderButton label="New chat about this page" onClick={() => {
          atlas.newChat()
          if (current) setAttached(current)
        }}><Plus className="h-4 w-4" /></HeaderButton>
        {chat && (
          <HeaderButton label="Continue in Atlas" onClick={() => void browser.tabs.create({ url: `${settings.base}/c/${chat.id}` })}>
            <ExternalLink className="h-4 w-4" />
          </HeaderButton>
        )}
        <HeaderButton label="Settings" onClick={() => setShowSettings(true)}><Settings className="h-4 w-4" /></HeaderButton>
      </header>
      <PageCard tab={attached} blocked={blockedReason} pdf={pdf} reading={reading} onReading={setReading}
                compact={Boolean(chat && chat.turns.length > 0)}
                onViewer={() => attached && void browser.tabs.update(attached.id, { url: viewerUrl(attached.url) })}
                onFill={() => attached && void suggestFill(attached, setFillStatus)} />
      {fillStatus && (
        <div className="flex items-start gap-2 border-b bg-muted/60 px-3 py-2 text-xs">
          <span className="min-w-0 flex-1 whitespace-pre-wrap">{fillStatus}</span>
          <button type="button" onClick={() => setFillStatus("")}>×</button>
        </div>
      )}
      {error && (
        <div className="flex items-start gap-2 border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          <span className="min-w-0 flex-1 whitespace-pre-wrap">{error}</span>
          <button type="button" onClick={atlas.clearError}>×</button>
        </div>
      )}
      <main className="min-h-0 flex-1">
        <AnswerExtras.Provider value={extras}>
          <ChatScreen layout="panel" composerExtra={readable && (
                        <button type="button" aria-label="Attach a screenshot of the page" title="Attach a screenshot of the page" onClick={takeScreenshot}
                                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground">
                          <Camera className="h-4 w-4" />
                        </button>
                      )}
                      emptyView={<PanelHome tab={attached && !blockedReason ? attached : null} reading={reading} blocked={blockedReason}
                                            onOpen={(c) => void openPast(c)} />}
                      placeholder={reading && attached && !blockedReason ? "Ask about this page…" : "Ask Atlas…"} />
        </AnswerExtras.Provider>
      </main>
    </div>
  )
}

function HeaderButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground">
      {children}
    </button>
  )
}
