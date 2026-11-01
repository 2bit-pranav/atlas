/**
 * The side panel: a chat with Atlas about the page in the current tab.
 *
 * The chat itself is the web UI's (`ChatScreen`, the shared store). What the
 * panel adds:
 *
 * - pairing with the backend: "Connect" opens Atlas's Browser extension page,
 *   which hands the token to the extension (the background worker keeps it);
 * - attaching the chat to one tab: messages carry that page, which turns on
 *   the page tools, and the store's client calls run in that tab;
 * - switching tabs offers a new chat or re-attaching, never silently reading
 *   another page;
 * - under each answer, the page passages it quoted, highlighted (or marked
 *   as not on the page);
 * - questions from the selection chip and the right-click menu;
 * - a PDF tab (the browser's viewer runs no content script) is sent as a file:
 *   before the chat's first message the PDF is attached, and the pdf skill
 *   reads it (OCR included);
 * - looking: `page_screenshot` / `page_image` are answered here (capturing a
 *   tab and fetching images are extension powers), and the camera button
 *   attaches a screenshot to the next message;
 * - Fill: the form's fields go to Atlas, suggested values come back as a
 *   preview on the page, and are filled only on Apply. Never submitted;
 * - history: the browser's own chats, reopened from a list, and the last chat
 *   back when the panel opens again on its page.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Camera, ExternalLink, History, Plus, Settings, TextCursorInput } from "lucide-react"
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
import { pageCall } from "./actions/pageCall"
import { usePendingAsks } from "./hooks/usePendingAsks"
import { sameUrl } from "./url"
import { QuoteSources } from "./components/QuoteSources"
import { Centered } from "./components/Centered"
import { SettingsView } from "./components/SettingsView"
import { HistoryView } from "./components/HistoryView"
import { PageChip } from "./components/PageChip"
import { suggestFill } from "./actions/suggestFill"

export function Panel() {
  const [settings, setSettings] = useState<ExtensionSettings | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  /** A reopened chat whose page is not this tab, after "Use this tab". */
  const [keepTab, setKeepTab] = useState<string | null>(null)
  const [current, setCurrent] = useState<TabInfo | null>(null)
  const [attached, setAttached] = useState<TabInfo | null>(null)
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

  // A new, empty chat follows the current tab; a chat with turns stays on its tab.
  useEffect(() => {
    if (!current) return
    if (!chat || chat.turns.length === 0 || current.id === attached?.id) setAttached(current)
  }, [current, chat, attached?.id])

  const blockedReason = settings && attached ? blocked(attached.url, settings.neverRead) : null
  // A PDF in the browser's own viewer: sent as a file. In the Atlas viewer it is a readable page.
  const pdf = attached !== null && !attached.viewer && !blockedReason && isPdf(attached.url)

  // The store sends the attached page with each message and runs client calls there.
  // A PDF has no content script: it goes as a file instead, attached once per chat.
  const sentPdfs = useRef(new Set<string>())
  useEffect(() => {
    const readable = attached && !blockedReason && !pdf
    atlas.origin = attached && !blockedReason ? { url: attached.url, title: attached.title } : null
    atlas.page = readable ? { url: attached.url, title: attached.title } : null
    atlas.onClientCall = readable ? (op, args) => pageCall(attached.id, op, args) : null
    atlas.beforeSend = pdf && attached ? async () => {
      const chatId = atlas.state.chat?.id ?? atlas.state.stagedChat ?? ""
      if (sentPdfs.current.has(`${chatId}|${attached.url}`)) return
      await atlas.attachSaved(pdfName(attached.url), (id) => savePdf(id, attached.url))
      sentPdfs.current.add(`${atlas.state.chat?.id ?? atlas.state.stagedChat ?? ""}|${attached.url}`)
    } : null
  }, [attached, blockedReason, pdf])

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

  /** Reopen a past chat: on its page when that page is the current tab, else with a banner. */
  const openPast = async (summary: ChatSummary) => {
    setShowHistory(false)
    setKeepTab(null)
    await atlas.openChat(summary.id)
    if (current) setAttached(current)
  }
  const [fillStatus, setFillStatus] = useState("")

  const extras = useMemo(() => (attached && !blockedReason && !pdf
    ? (turn: Turn, answer: string) => <QuoteSources turn={turn} answer={answer} tabId={attached.id} />
    : null), [attached, blockedReason, pdf])

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

  const elsewhere = chat && chat.turns.length > 0 && current && attached && current.id !== attached.id
  // A reopened chat about a page that is not the attached tab.
  const aboutOther = !elsewhere && chat && chat.turns.length > 0 && chat.page_url && attached &&
    !sameUrl(chat.page_url, attached.url) && keepTab !== chat.id

  if (showHistory) return <HistoryView onOpen={(c) => void openPast(c)} onClose={() => setShowHistory(false)} />

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <PageChip tab={attached} blocked={blockedReason} pdf={pdf} />
        {attached && pdf && (
          <button type="button" title="Open in the Atlas viewer: read, find and highlight beside this chat"
                  onClick={() => void browser.tabs.update(attached.id, { url: viewerUrl(attached.url) })}
                  className="shrink-0 rounded-md border px-2 py-1 text-xs hover:bg-accent">Open in Atlas viewer</button>
        )}
        {attached && !blockedReason && !pdf && (
          <>
            <button type="button" title="Attach a screenshot of the page to your next message" onClick={async () => {
              const shot = await screenshot(attached.id)
              if ("error" in shot) return void atlas.fail(new Error(shot.error))
              await atlas.attach_files([dataUrlToFile(`data:image/jpeg;base64,${shot.data}`, "screenshot.jpg")])
            }} className="rounded-md p-1.5 hover:bg-accent"><Camera className="h-4 w-4" /></button>
            {!attached.viewer && (
              <button type="button" title="Suggest values for this page's form from your details" onClick={() => void suggestFill(attached, setFillStatus)}
                      className="rounded-md p-1.5 hover:bg-accent"><TextCursorInput className="h-4 w-4" /></button>
            )}
          </>
        )}
        <button type="button" title="New chat about this page" onClick={() => {
          atlas.newChat()
          if (current) setAttached(current)
        }} className="rounded-md p-1.5 hover:bg-accent"><Plus className="h-4 w-4" /></button>
        {chat && (
          <button type="button" title="Continue in Atlas" onClick={() => void browser.tabs.create({ url: `${settings.base}/c/${chat.id}` })}
                  className="rounded-md p-1.5 hover:bg-accent"><ExternalLink className="h-4 w-4" /></button>
        )}
        <button type="button" title="Browser chats" onClick={() => {
          setShowHistory(true)
          void atlas.refreshChats()
        }} className="rounded-md p-1.5 hover:bg-accent"><History className="h-4 w-4" /></button>
        <button type="button" title="Settings" onClick={() => setShowSettings(true)}
                className="rounded-md p-1.5 hover:bg-accent"><Settings className="h-4 w-4" /></button>
      </header>
      {elsewhere && (
        <div className="flex flex-wrap items-center gap-2 border-b bg-muted/60 px-3 py-2 text-xs">
          <span className="min-w-0 flex-1">This chat is about “{attached.title}”. You are on another tab now.</span>
          <button type="button" className="rounded-md border px-2 py-1 hover:bg-accent" onClick={() => {
            atlas.newChat()
            setAttached(current)
          }}>New chat here</button>
          <button type="button" className="rounded-md border px-2 py-1 hover:bg-accent" onClick={() => setAttached(current)}>
            Use this tab
          </button>
        </div>
      )}
      {aboutOther && (
        <div className="flex flex-wrap items-center gap-2 border-b bg-muted/60 px-3 py-2 text-xs">
          <span className="min-w-0 flex-1">This chat was about “{chat.page_title || chat.page_url}”, not this tab.</span>
          <button type="button" className="rounded-md border px-2 py-1 hover:bg-accent" onClick={async () => {
            const open = (await browser.tabs.query({})).find((t) => t.url && sameUrl(t.url, chat.page_url!))
            const tab = open?.id !== undefined
              ? await browser.tabs.update(open.id, { active: true })
              : await browser.tabs.create({ url: chat.page_url! })
            if (tab?.id !== undefined)
              setAttached({ id: tab.id, url: chat.page_url!, title: tab.title || chat.page_title || "", favIconUrl: tab.favIconUrl })
          }}>Open that page</button>
          <button type="button" className="rounded-md border px-2 py-1 hover:bg-accent" onClick={() => setKeepTab(chat.id)}>
            Use this tab
          </button>
        </div>
      )}
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
          <ChatScreen />
        </AnswerExtras.Provider>
      </main>
    </div>
  )
}
