/**
 * The side panel: a chat with Atlas about the page in the current tab.
 *
 * The chat itself is the web UI's (`ChatScreen`, the shared store). What the
 * panel adds:
 *
 * - pairing with the backend (the token from Atlas > Settings > Browser extension);
 * - attaching the chat to one tab: messages carry that page, which turns on
 *   the page tools, and the store's client calls run in that tab;
 * - switching tabs offers a new chat or re-attaching, never silently reading
 *   another page;
 * - under each answer, the page passages it quoted, highlighted (or marked
 *   as not on the page);
 * - questions from the selection chip and the right-click menu;
 * - a PDF tab (the browser's viewer runs no content script) is sent as a file:
 *   before the chat's first message the PDF is attached, and the pdf skill
 *   reads it (OCR included).
 */

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { ExternalLink, Globe, Plus, Settings, ShieldOff } from "lucide-react"

import * as api from "@/lib/api"
import { atlas, useAtlas } from "@/lib/store"
import { AnswerExtras } from "@/lib/slots"
import type { Turn } from "@/lib/types"
import { ChatScreen } from "@/components/chat/ChatScreen"
import { cn } from "@/lib/utils"
import { blocked, loadSettings, saveSettings, type ExtensionSettings, type PendingAsk } from "@ext/settings"
import { activeTab, tabCall, type TabInfo } from "@ext/tab"

type Status = "loading" | "unpaired" | "offline" | "ready"

export function Panel() {
  const [settings, setSettings] = useState<ExtensionSettings | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [showSettings, setShowSettings] = useState(false)
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
    void loadSettings().then((s) => {
      setSettings(s)
      void connect(s)
    })
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
  const pdf = attached !== null && !blockedReason && isPdf(attached.url)

  // The store sends the attached page with each message and runs client calls there.
  // A PDF has no content script: it goes as a file instead, attached once per chat.
  const sentPdfs = useRef(new Set<string>())
  useEffect(() => {
    const readable = attached && !blockedReason && !pdf
    atlas.origin = attached && !blockedReason ? { url: attached.url, title: attached.title } : null
    atlas.page = readable ? { url: attached.url, title: attached.title } : null
    atlas.onClientCall = readable ? (op, args) => tabCall(attached.id, op, args) : null
    atlas.beforeSend = pdf && attached ? async () => {
      const chatId = atlas.state.chat?.id ?? atlas.state.stagedChat ?? ""
      if (sentPdfs.current.has(`${chatId}|${attached.url}`)) return
      await atlas.attachSaved(pdfName(attached.url), (id) => savePdf(id, attached.url))
      sentPdfs.current.add(`${atlas.state.chat?.id ?? atlas.state.stagedChat ?? ""}|${attached.url}`)
    } : null
  }, [attached, blockedReason, pdf])

  usePendingAsks(status === "ready", setAttached)

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
          const next = await saveSettings(patch)
          setSettings(next)
          setShowSettings(false)
          await connect(next)
        }}
        onClose={status === "ready" ? () => setShowSettings(false) : undefined}
      />
    )

  const elsewhere = chat && chat.turns.length > 0 && current && attached && current.id !== attached.id

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <PageChip tab={attached} blocked={blockedReason} pdf={pdf} />
        <button type="button" title="New chat about this page" onClick={() => {
          atlas.newChat()
          if (current) setAttached(current)
        }} className="rounded-md p-1.5 hover:bg-accent"><Plus className="h-4 w-4" /></button>
        {chat && (
          <button type="button" title="Continue in Atlas" onClick={() => void browser.tabs.create({ url: `${settings.base}/c/${chat.id}` })}
                  className="rounded-md p-1.5 hover:bg-accent"><ExternalLink className="h-4 w-4" /></button>
        )}
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

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-dvh items-center justify-center p-6 text-center text-sm text-muted-foreground">{children}</div>
}

/** What Atlas can see: the attached page, or why it cannot read it. */
function PageChip({ tab, blocked: reason, pdf }: { tab: TabInfo | null; blocked: string | null; pdf: boolean }) {
  let host = ""
  try {
    host = tab ? new URL(tab.url).hostname : ""
  } catch {
    host = ""
  }
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2" title={tab?.url}>
      {reason ? <ShieldOff className="h-4 w-4 shrink-0 text-muted-foreground" />
        : tab?.favIconUrl ? <img src={tab.favIconUrl} alt="" className="h-4 w-4 shrink-0" />
        : <Globe className="h-4 w-4 shrink-0 text-muted-foreground" />}
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{tab?.title || "No page"}</p>
        <p className={cn("truncate text-[11px]", reason ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
          {reason ? `Not read: ${reason}` : pdf ? `PDF · read as a file${host ? ` · ${host}` : ""}` : `Atlas can read this page · ${host}`}
        </p>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------- PDFs --

function isPdf(url: string): boolean {
  try {
    const parsed = new URL(url)
    return /\.pdf$/i.test(decodeURIComponent(parsed.pathname)) && /^(https?|file):$/.test(parsed.protocol)
  } catch {
    return false
  }
}

function pdfName(url: string): string {
  try {
    const name = decodeURIComponent(new URL(url).pathname.split("/").pop() ?? "")
    return name || "document.pdf"
  } catch {
    return "document.pdf"
  }
}

/**
 * The tab's PDF into the chat. A web PDF is fetched here, with the user's
 * session, so one behind a login works; if that fails, and for `file://`,
 * the backend copies it (no "allow access to file URLs" switch needed).
 */
async function savePdf(chatId: string, url: string) {
  if (/^https?:/i.test(url)) {
    try {
      const response = await fetch(url, { credentials: "include" })
      const blob = await response.blob()
      const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer())
      if (response.ok && String.fromCharCode(...head) === "%PDF")
        return await api.uploadFile(chatId, new File([blob], pdfName(url), { type: "application/pdf" }))
    } catch {
      /* the backend tries next */
    }
  }
  return api.importFile(chatId, url)
}

// ------------------------------------------------------------ quote sources --

const QUOTE = /[“"]([^”"\n]{12,300})[”"]/g

/**
 * The passages an answer quoted, found on the page and highlighted. A quote
 * the page does not contain is shown as such: with a small model, that is
 * how an unsupported claim becomes visible.
 */
function QuoteSources({ turn, answer, tabId }: { turn: Turn; answer: string; tabId: number }) {
  const quotes = useMemo(() => Array.from(new Set(Array.from(answer.matchAll(QUOTE), (m) => m[1].trim()))).slice(0, 8), [answer])
  const latest = useAtlas((s) => s.chat?.turns.at(-1)?.id === turn.id)
  const [found, setFound] = useState<boolean[] | null>(null)
  const extrasActive = useContext(AnswerExtras) !== null

  const check = useCallback(async () => {
    const result = await tabCall(tabId, "highlight", { quotes })
    setFound(Array.isArray(result.found) ? (result.found as boolean[]) : quotes.map(() => false))
  }, [quotes, tabId])

  useEffect(() => {
    if (latest && quotes.length && extrasActive) void check()
  }, [latest, quotes.length, extrasActive, check])

  if (!quotes.length) return null
  return (
    <div className="mt-3 rounded-lg border bg-muted/30 p-2 text-xs">
      <p className="mb-1.5 font-medium text-muted-foreground">On this page</p>
      <ul className="space-y-1">
        {quotes.map((q, i) => {
          const ok = found?.[i]
          return (
            <li key={q}>
              <button type="button" disabled={found !== null && !ok}
                      onClick={async () => {
                        if (!found || !latest) await check()
                        await tabCall(tabId, "scrollToQuote", { index: i })
                      }}
                      className={cn("w-full rounded-md px-2 py-1 text-left leading-snug hover:bg-accent disabled:cursor-default disabled:hover:bg-transparent",
                                    found !== null && !ok && "text-destructive")}>
                <span className="mr-1">{found === null ? "·" : ok ? "✓" : "✗"}</span>
                “{q.length > 110 ? `${q.slice(0, 110)}…` : q}”
                {found !== null && !ok && <span className="ml-1 italic">not found on the page</span>}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------- pending asks --

const PROMPTS: Record<PendingAsk["action"], (text: string, language?: string) => string> = {
  explain: (t) => `Explain this passage from the page in simple terms:\n\n“${t}”`,
  simplify: (t) => `Rewrite this passage from the page in simpler words, keeping its meaning:\n\n“${t}”`,
  define: (t) => `Define the key terms in this passage, as they are used on this page:\n\n“${t}”`,
  translate: (t, l) => `Translate this passage into ${l ?? "English"}. Reply with the translation only:\n\n“${t}”`,
  ask: (t) => `What does this passage from the page mean?\n\n“${t}”`,
}

/** Questions left by the selection chip or the right-click menu: a new chat on that tab. */
function usePendingAsks(ready: boolean, attach: (tab: TabInfo) => void) {
  const busy = useAtlas((s) => s.run !== null)
  const handled = useRef(0)
  useEffect(() => {
    if (!ready) return
    const take = async () => {
      const { pendingAsk } = (await browser.storage.session.get("pendingAsk")) as { pendingAsk?: PendingAsk }
      if (!pendingAsk || pendingAsk.at <= handled.current || atlas.busy) return
      handled.current = pendingAsk.at
      await browser.storage.session.remove("pendingAsk")
      const tab = await browser.tabs.get(pendingAsk.tabId)
      const info: TabInfo = { id: pendingAsk.tabId, url: tab.url ?? "", title: tab.title ?? "", favIconUrl: tab.favIconUrl }
      atlas.newChat()
      attach(info)
      atlas.page = { url: info.url, title: info.title }
      atlas.onClientCall = (op, args) => tabCall(info.id, op, args)
      await atlas.send(PROMPTS[pendingAsk.action](pendingAsk.text.slice(0, 4000), pendingAsk.language))
    }
    void take()
    const onChange = (changes: Record<string, unknown>, area: string) => {
      if (area === "session" && "pendingAsk" in changes) void take()
    }
    browser.storage.onChanged.addListener(onChange)
    return () => browser.storage.onChanged.removeListener(onChange)
  }, [ready, attach, busy])
}

// ------------------------------------------------------------------ settings --

function SettingsView({ settings, status, onSave, onClose }: {
  settings: ExtensionSettings
  status: Status
  onSave: (patch: Partial<ExtensionSettings>) => Promise<void>
  onClose?: () => void
}) {
  const [draft, setDraft] = useState({
    base: settings.base, token: settings.token, neverRead: settings.neverRead.join("\n"),
    tablesFolder: settings.tablesFolder, languages: settings.languages.join(", "),
  })
  const field = "w-full rounded-md border bg-background px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/30"
  return (
    <div className="h-dvh overflow-y-auto p-4 text-sm">
      <h1 className="text-base font-semibold">Atlas</h1>
      {status === "unpaired" && (
        <p className="mt-2 rounded-md bg-muted p-2.5 text-xs leading-relaxed">
          Pair this extension with Atlas: in Atlas, open <b>Settings › Browser extension</b>, copy the pairing token, and paste it below.
        </p>
      )}
      {status === "offline" && (
        <p className="mt-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          Atlas is not answering at {settings.base}. Start it with <code>atlas start</code>, then Save to try again.
        </p>
      )}
      <label className="mt-4 block text-xs font-medium">Pairing token</label>
      <input type="password" className={cn(field, "mt-1 font-mono")} value={draft.token}
             onChange={(e) => setDraft({ ...draft, token: e.target.value.trim() })} placeholder="Paste the token" />
      <label className="mt-4 block text-xs font-medium">Never read these sites</label>
      <p className="text-[11px] text-muted-foreground">One per line, e.g. mybank.com (subdomains included). Atlas will not read or highlight them.</p>
      <textarea rows={4} className={cn(field, "mt-1 font-mono text-xs")} value={draft.neverRead}
                onChange={(e) => setDraft({ ...draft, neverRead: e.target.value })} />
      <label className="mt-4 block text-xs font-medium">Save tables to</label>
      <input className={cn(field, "mt-1 font-mono text-xs")} value={draft.tablesFolder} placeholder="Downloads/Atlas"
             onChange={(e) => setDraft({ ...draft, tablesFolder: e.target.value })} />
      <label className="mt-4 block text-xs font-medium">Translate into</label>
      <input className={cn(field, "mt-1")} value={draft.languages}
             onChange={(e) => setDraft({ ...draft, languages: e.target.value })} />
      <label className="mt-4 block text-xs font-medium">Atlas address</label>
      <input className={cn(field, "mt-1 font-mono text-xs")} value={draft.base}
             onChange={(e) => setDraft({ ...draft, base: e.target.value.trim() })} />
      <div className="mt-5 flex gap-2">
        <button type="button" className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
                onClick={() => void onSave({
                  base: draft.base || "http://127.0.0.1:8000", token: draft.token,
                  neverRead: draft.neverRead.split("\n").map((s) => s.trim()).filter(Boolean),
                  tablesFolder: draft.tablesFolder.trim(),
                  languages: draft.languages.split(",").map((s) => s.trim()).filter(Boolean),
                })}>Save</button>
        {onClose && <button type="button" className="rounded-md border px-3 py-1.5" onClick={onClose}>Back</button>}
      </div>
    </div>
  )
}
