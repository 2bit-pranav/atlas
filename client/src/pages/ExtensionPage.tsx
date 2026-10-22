/**
 * The browser extension: whether it is installed and connected, one-click
 * Connect, and the details its fill suggestions use.
 *
 * The page and the extension talk with `postMessage`: the extension's content
 * script runs on this page (it is on 127.0.0.1 or localhost) and answers
 * `atlas:hello` with whether it is connected to this Atlas. Connect hands it
 * the pairing token, which the extension checks against the backend before
 * keeping. The token itself is only shown in developer mode.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { CheckCircle2, Circle, Loader2, PanelRight } from "lucide-react"

import * as api from "@/lib/api"
import { usePrefs } from "@/lib/prefs"
import { Button, Notice, PageShell } from "@/components/ui/kit"
import { cn } from "@/lib/utils"

type State = "checking" | "missing" | "unpaired" | "connected"
type Answer = { connected?: boolean; error?: string; version?: string }

/** One question to the extension; null when nothing answers (not installed, or the page loaded before it). */
function ask(message: Record<string, unknown>, wait = 1500): Promise<Answer | null> {
  return new Promise((resolve) => {
    const done = (answer: Answer | null) => {
      removeEventListener("message", listen)
      clearTimeout(timer)
      resolve(answer)
    }
    const listen = (event: MessageEvent) => {
      if (event.source === window && event.data?.type === "atlas:here") done(event.data as Answer)
    }
    addEventListener("message", listen)
    const timer = setTimeout(() => done(null), wait)
    postMessage(message, location.origin)
  })
}

export function ExtensionPage() {
  const { devMode } = usePrefs()
  const [params, setParams] = useSearchParams()
  const [state, setState] = useState<State>("checking")
  const [version, setVersion] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const base = useRef("")

  const check = useCallback(async () => {
    if (!base.current) base.current = (await api.getPairing()).base
    // The content script may still be loading: ask a few times before giving up.
    for (let i = 0; i < 3; i++) {
      const answer = await ask({ type: "atlas:hello", base: base.current }, 800)
      if (answer) {
        setVersion(answer.version ?? "")
        setState(answer.connected ? "connected" : "unpaired")
        return answer.connected ? "connected" : "unpaired"
      }
    }
    setState("missing")
    return "missing"
  }, [])

  const connect = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const { token, base: at } = await api.getPairing()
      base.current = at
      const answer = await ask({ type: "atlas:pair", token, base: at }, 5000)
      if (!answer) setState("missing")
      else if (answer.connected) setState("connected")
      else setError(answer.error ?? "The extension could not connect.")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [])

  // `?connect=1`: opened from the extension's own Connect button.
  useEffect(() => {
    void check().then((found) => {
      if (params.get("connect") && found === "unpaired") void connect()
      if (params.get("connect")) setParams({}, { replace: true })
    }).catch((e) => {
      setState("missing")
      setError(e instanceof Error ? e.message : String(e))
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <PageShell title="Browser extension"
               description="A side panel in Edge or Chrome that reads the page you are on, with the same agent, tools and chats.">
      <StatusCard state={state} version={version} busy={busy} onConnect={() => void connect()} onRecheck={() => void check()} />
      {error && <div className="mt-3"><Notice tone="error" onClose={() => setError(null)}>{error}</Notice></div>}
      {state === "missing" && <Install devMode={devMode} />}
      {state === "connected" && <Uses />}
      <ProfileGroup />
      {devMode && <TokenGroup onReset={() => void check()} />}
    </PageShell>
  )
}

function StatusCard({ state, version, busy, onConnect, onRecheck }: {
  state: State; version: string; busy: boolean; onConnect: () => void; onRecheck: () => void
}) {
  const text = {
    checking: ["Looking for the extension…", ""],
    missing: ["Not installed in this browser", "Install it below, then come back to this page."],
    unpaired: ["Installed, not connected", "Connect it to this Atlas. It only works with Atlas once connected."],
    connected: ["Connected", "Click the Atlas icon in the browser's toolbar to open the side panel on any page."],
  }[state]
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-xl border bg-card p-4">
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                          state === "connected" ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" : "bg-muted text-muted-foreground")}>
        {state === "checking" ? <Loader2 className="h-4 w-4 animate-spin" />
          : state === "connected" ? <CheckCircle2 className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{text[0]}{version && state !== "missing" && <span className="ml-2 text-xs font-normal text-muted-foreground">v{version}</span>}</p>
        {text[1] && <p className="mt-0.5 text-xs text-muted-foreground">{text[1]}</p>}
      </div>
      {state === "unpaired" && <Button onClick={onConnect} disabled={busy}>{busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}Connect</Button>}
      {state === "missing" && <Button variant="outline" onClick={onRecheck}>Check again</Button>}
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="rounded-xl border bg-card">{children}</div>
    </section>
  )
}

const code = "rounded bg-muted px-1 py-px font-mono text-xs"

function Install({ devMode }: { devMode: boolean }) {
  return (
    <Group title="Install">
      <ol className="list-decimal space-y-2 py-3 pl-9 pr-4 text-sm text-muted-foreground">
        {devMode && (
          <li>Build it: <code className={code}>cd extension</code>, <code className={code}>npm install</code>, <code className={code}>npm run build</code>.</li>
        )}
        <li>Open <code className={code}>edge://extensions</code> (or <code className={code}>chrome://extensions</code>) and turn on <b className="font-medium text-foreground">Developer mode</b>.</li>
        <li><b className="font-medium text-foreground">Load unpacked</b>, and choose the <code className={code}>extension/.output/chrome-mv3</code> folder inside Atlas.</li>
        <li>Reload this page and click <b className="font-medium text-foreground">Connect</b>.</li>
      </ol>
    </Group>
  )
}

function Uses() {
  const items = [
    ["Ask about the page", "Open the side panel; answers quote the page and highlight where."],
    ["Select text", "Explain, Simplify, Define or Translate from the chip that appears."],
    ["PDFs", "Open a PDF in the Atlas viewer from the panel, to read and highlight it side by side."],
    ["Tables", "Select inside a table, or right-click it, to save it as a spreadsheet."],
    ["Forms", "Fill suggests values from your details below. Nothing is filled until you apply it."],
  ]
  return (
    <Group title="What it does">
      <ul className="divide-y">
        {items.map(([title, text]) => (
          <li key={title} className="flex gap-3 px-4 py-2.5">
            <PanelRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="text-sm"><b className="font-medium">{title}.</b> <span className="text-muted-foreground">{text}</span></span>
          </li>
        ))}
      </ul>
    </Group>
  )
}

/** The details the extension's fill suggestions use. They stay in Atlas. */
function ProfileGroup() {
  const [text, setText] = useState<string | null>(null)
  const [saved, setSaved] = useState("")
  useEffect(() => {
    api.getProfile().then((r) => {
      setText(r.text)
      setSaved(r.text)
    }).catch(() => setText(""))
  }, [])
  return (
    <Group title="Your details">
      <div className="space-y-2 px-4 py-3">
        <p className="text-xs text-muted-foreground">
          For form fill suggestions. One detail per line, in your own words. They stay on this computer:
          the extension never reads them, it only gets the values for a form's fields.
        </p>
        <textarea rows={7} value={text ?? ""} onChange={(e) => setText(e.target.value)}
                  placeholder={"Name: Your Name\nRoll no: 21CS045\nEmail: you@example.com\nPhone: +91 98765 43210\nDate of birth: 4 March 2004\nAddress: 12 Lake Road, Pune 411001"}
                  className="w-full rounded-md border bg-background p-2.5 font-mono text-xs leading-relaxed outline-none focus:ring-2 focus:ring-ring/30" />
        <div className="flex justify-end">
          <Button size="sm" disabled={text === null || text === saved} onClick={async () => {
            const r = await api.putProfile(text ?? "")
            setSaved(r.text)
          }}>{text !== null && text !== saved ? "Save details" : "Saved"}</Button>
        </div>
      </div>
    </Group>
  )
}

/** Developer mode only: the raw pairing token, for pasting by hand or revoking. */
function TokenGroup({ onReset }: { onReset: () => void }) {
  const [token, setToken] = useState("")
  const [shown, setShown] = useState(false)
  const [copied, setCopied] = useState(false)
  const [confirm, setConfirm] = useState(false)
  useEffect(() => {
    api.getPairing().then((r) => setToken(r.token)).catch(() => setToken(""))
  }, [])
  const copy = async () => {
    await navigator.clipboard.writeText(token)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Group title="Pairing token">
      <div className="space-y-3 px-4 py-3">
        <p className="text-xs text-muted-foreground">
          Connect hands this to the extension. Only a holder of it can use Atlas from outside this page; other websites are refused.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-md border bg-muted/50 px-2 py-1.5 font-mono text-xs">
            {token ? (shown ? token : "•".repeat(24)) : "unavailable"}
          </code>
          <Button size="sm" variant="outline" onClick={() => setShown(!shown)}>{shown ? "Hide" : "Show"}</Button>
          <Button size="sm" variant="outline" onClick={() => void copy()} disabled={!token}>{copied ? "Copied" : "Copy"}</Button>
          {confirm ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
              <Button size="sm" onClick={async () => {
                setToken((await api.resetPairing()).token)
                setConfirm(false)
                onReset()
              }}>Make a new token</Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirm(true)} title="Disconnects the extension until it is connected again">Reset…</Button>
          )}
        </div>
      </div>
    </Group>
  )
}
