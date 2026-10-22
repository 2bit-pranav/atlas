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

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, Camera, ExternalLink, Globe, History, Plus, Search, Settings, ShieldOff, TextCursorInput, Trash2 } from "lucide-react"

import * as api from "@/lib/api"
import { atlas, useAtlas } from "@/lib/store"
import { AnswerExtras } from "@/lib/slots"
import type { ChatSummary, Turn } from "@/lib/types"
import { fullTime, timeAgo, useNow } from "@/lib/time"
import { ChatScreen } from "@/components/chat/ChatScreen"
import { cn } from "@/lib/utils"
import { blocked, loadSettings, saveSettings, type ExtensionSettings, type PendingAsk } from "@ext/settings"
import { activeTab, tabCall, toTabInfo, viewerUrl, type TabInfo } from "@ext/tab"
import { dataUrlToFile, fetchImage, screenshot } from "@ext/images"

type Status = "loading" | "unpaired" | "offline" | "ready"

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
          {reason ? `Not read: ${reason}` : pdf ? `PDF · read as a file${host ? ` · ${host}` : ""}`
            : tab?.viewer ? `PDF in the Atlas viewer${host ? ` · ${host}` : " · on this computer"}` : `Atlas can read this page · ${host}`}
        </p>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ history --

/** The same page, ignoring the #fragment. */
function sameUrl(a: string, b: string): boolean {
  return a.split("#")[0] === b.split("#")[0]
}

function host(url: string | undefined): string {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, "") : ""
  } catch {
    return ""
  }
}

/** The chats started in the browser, newest first. The web UI keeps all of them, grouped with the rest. */
function HistoryView({ onOpen, onClose }: { onOpen: (c: ChatSummary) => void; onClose: () => void }) {
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

// ------------------------------------------------------------ page calls --

/** A page operation for the attached tab: looking is done here, the rest by the content script. */
async function pageCall(tabId: number, op: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (op === "screenshot") return screenshot(tabId)
  if (op === "image") {
    const found = await tabCall(tabId, "imageSrc", args)
    if (found.error || typeof found.src !== "string") return found
    const image = await fetchImage(found.src)
    return "error" in image ? image : { data: image.data, format: image.format }
  }
  return tabCall(tabId, op, args)
}

// --------------------------------------------------------------------- fill --

/** Fields out, suggestions back, shown on the page. Filling waits for the user's Apply there. */
async function suggestFill(tab: TabInfo, status: (s: string) => void) {
  status("Reading the form…")
  const found = await tabCall(tab.id, "formFields")
  if (found.error) return status(String(found.error))
  const fields = (found.fields as { id: string; label: string }[]) ?? []
  if (!fields.length) return status("No fields to fill on this page (passwords, codes and card numbers are never filled).")
  status(`Matching ${fields.length} fields to your details…`)
  try {
    const { values, missing } = await api.suggestFill(fields, String(found.title ?? tab.title))
    const shown = await tabCall(tab.id, "previewFill", { values })
    const n = Number(shown.shown ?? 0)
    status(n
      ? `Suggested ${n} value${n === 1 ? "" : "s"}: check them on the page, then Apply there. Nothing is submitted.` +
        (missing.length ? `\nNot in your details: ${missing.slice(0, 8).join(", ")}${missing.length > 8 ? "…" : ""}` : "")
      : "Your details did not answer any of this form's fields.")
  } catch (error) {
    status(error instanceof Error ? error.message : String(error))
  }
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
                {found !== null && !ok && <span className="ml-1 italic">not in the page's text (may be from an image)</span>}
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
  image: () => "What does this image from the page show? If it has text, read it out exactly.",
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
      const info = toTabInfo(tab)
      if (!info) return
      atlas.newChat()
      attach(info)
      atlas.page = { url: info.url, title: info.title }
      atlas.onClientCall = (op, args) => pageCall(info.id, op, args)
      if (pendingAsk.action === "image" && pendingAsk.src) {
        const image = await fetchImage(pendingAsk.src)
        if ("error" in image) return void atlas.fail(new Error(image.error))
        const ext = image.format === "jpeg" ? "jpg" : image.format
        await atlas.attach_files([new File([image.blob], `image.${ext}`, { type: image.blob.type })])
      }
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
        <div className="mt-3 rounded-lg border bg-muted/40 p-3">
          <p className="text-sm font-medium">Connect to Atlas</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Opens Atlas in a tab and connects this extension. Atlas has to be running (<code>atlas start</code>).
          </p>
          <button type="button" className="mt-2.5 w-full rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
                  onClick={() => void browser.tabs.create({ url: `${settings.base.replace(/\/$/, "")}/extension?connect=1` })}>
            Connect
          </button>
        </div>
      )}
      {status === "offline" && (
        <p className="mt-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          Atlas is not answering at {settings.base}. Start it with <code>atlas start</code>, then Save to try again.
        </p>
      )}
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
      <details className="mt-4">
        <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Advanced</summary>
        <label className="mt-3 block text-xs font-medium">Atlas address</label>
        <input className={cn(field, "mt-1 font-mono text-xs")} value={draft.base}
               onChange={(e) => setDraft({ ...draft, base: e.target.value.trim() })} />
        <label className="mt-3 block text-xs font-medium">Pairing token</label>
        <p className="text-[11px] text-muted-foreground">Set by Connect. Paste one only if Connect cannot reach Atlas.</p>
        <input type="password" className={cn(field, "mt-1 font-mono")} value={draft.token}
               onChange={(e) => setDraft({ ...draft, token: e.target.value.trim() })} placeholder="Pairing token" />
      </details>
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
