/** The panel's settings: connect, never-read sites, tables folder, languages. */

import { useState } from "react"
import { cn } from "@/lib/cn"
import { type ExtensionSettings } from "@ext/shared/settings"
import { Status } from "../status"

// ------------------------------------------------------------------ settings --

export function SettingsView({ settings, status, onSave, onClose }: {
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
