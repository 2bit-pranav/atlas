/**
 * Settings, as a page with sections rather than one long modal.
 *
 * Edits are a draft until Save, so a half-typed system prompt never reaches
 * the agent. LIVE keys apply from the next message. RESTART keys are saved and
 * badged; the "Restart now" notice lists only those that differ from what the
 * running servers were started with (the backend's `pending_restart`).
 */

import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { Download, Keyboard, MessagesSquare, Monitor, RotateCcw, Search, Upload, X } from "lucide-react"

import * as api from "@/lib/api"
import { atlas, useAtlas } from "@/lib/store"
import { setPrefs, usePrefs } from "@/lib/prefs"
import { SECTIONS, HIDDEN, describedKeys, type Field } from "@/lib/settingsSchema"
import { SHORTCUTS } from "@/lib/shortcuts"
import { downloadJson } from "@/lib/download"
import { Button, Kbd, Notice, Switch } from "@/components/ui/kit"
import type { ModelList } from "@/lib/types"
import { cn } from "@/lib/utils"

const navItem = (id: string) => ({ id, title: SECTIONS.find((s) => s.id === id)?.title ?? id })
/** Most-used first: what changes results, then the model; tuning under Advanced. */
const NAV = [
  { id: "general", title: "General" },
  navItem("agent"),
  { id: "extensions", title: "Skills & MCP" },
  navItem("access"),
  navItem("model"),
  { id: "conversations", title: "Conversations" },
  { id: "shortcuts", title: "Shortcuts" },
]
const ADVANCED = SECTIONS.filter((s) => s.advanced).map((s) => ({ id: s.id, title: s.title }))

export function SettingsPage() {
  const { section = "general" } = useParams()
  const navigate = useNavigate()
  const settings = useAtlas((s) => s.settings)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    void atlas.refreshSettings()
    void atlas.checkRestart()
  }, [])

  const dirty = Object.keys(draft).length > 0
  const values = useMemo(() => settings?.values ?? {}, [settings])
  const value = (key: string) => (key in draft ? draft[key] : values[key])
  const set = (key: string, v: unknown) => {
    setSaved(false)
    setDraft((d) => {
      const next = { ...d, [key]: v }
      if (JSON.stringify(v) === JSON.stringify(values[key])) delete next[key]
      return next
    })
  }

  const save = async () => {
    if (await atlas.saveSettings(draft)) {
      setDraft({})
      setSaved(true)
    }
  }

  const pending = Object.keys(settings?.pending_restart ?? {})
  const restarting = useAtlas((s) => s.restarting)
  const restartError = useAtlas((s) => s.restartError)
  const answering = useAtlas((s) => s.run !== null)
  const [query, setQuery] = useState("")
  const q = query.trim().toLowerCase()
  // Every described field that matches, with its section, across all sections.
  const matches = useMemo(() => !q ? [] : SECTIONS.flatMap((s) => s.groups.flatMap((g) =>
    g.fields.filter((f) => f.key in values &&
      [f.label, f.help ?? "", f.key, g.title].some((t) => t.toLowerCase().includes(q)))
      .map((f) => ({ field: f, where: `${s.title} · ${g.title}` })))), [q, values])

  return (
    <div className="flex h-full min-h-0">
      <nav className="hidden w-48 shrink-0 border-r px-3 py-6 md:block">
        <Link to="/" className="px-2 text-xs text-muted-foreground hover:text-foreground">← Back to chat</Link>
        <p className="mt-4 px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Settings</p>
        <SettingsSearch value={query} onChange={setQuery} />
        {[{ title: "", items: NAV }, { title: "Advanced", items: ADVANCED }].map((list) => (
          <ul key={list.title} className="mt-2 space-y-0.5">
            {list.title && <li className="px-2 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{list.title}</li>}
            {list.items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => navigate(`/settings/${item.id}`)}
                  className={cn("w-full rounded-md px-2 py-1.5 text-left text-sm",
                    section === item.id ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground")}
                >
                  {item.title}
                </button>
              </li>
            ))}
          </ul>
        ))}
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 pb-24 pt-6 sm:px-8">
            <select
              value={section}
              onChange={(e) => navigate(`/settings/${e.target.value}`)}
              className="mb-4 h-9 w-full rounded-lg border bg-background px-2 text-sm md:hidden"
            >
              {NAV.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
              <optgroup label="Advanced">
                {ADVANCED.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
              </optgroup>
            </select>
            <div className="mb-4 md:hidden"><SettingsSearch value={query} onChange={setQuery} /></div>

            {/* Only while a restart is pending, running, or has failed. */}
            {(pending.length > 0 || restartError || restarting) && (
              <Notice tone={restartError && !restarting ? "error" : "info"}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">
                    {restarting ? "Restarting llama-server and the backend..."
                      : restartError ? `The last restart failed: ${restartError}`
                      : <>{pending.length} saved {pending.length === 1 ? "setting takes" : "settings take"} effect
                          after a restart: {pending.join(", ")}</>}
                  </span>
                  <Button size="sm" onClick={() => void atlas.restart()} disabled={restarting || answering}>
                    {restarting ? "Restarting..." : "Restart now"}
                  </Button>
                </div>
              </Notice>
            )}

            {q && (
              <div>
                <SectionHead title={`Results for "${query.trim()}"`} text={matches.length ? `${matches.length} setting${matches.length > 1 ? "s" : ""}` : "No setting matches. Try another word."} />
                {matches.length > 0 && (
                  <div className="mt-4 divide-y rounded-xl border bg-card">
                    {matches.map(({ field, where }) => (
                      <div key={field.key}>
                        <p className="px-4 pt-2.5 text-[11px] uppercase tracking-wide text-muted-foreground/70">{where}</p>
                        <FieldRow field={field} value={value(field.key)} restart={settings?.tiers[field.key] === "restart"}
                                  changed={field.key in draft} onChange={(v) => set(field.key, v)} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {!q && section === "general" && <GeneralSection />}
            {!q && SECTIONS.filter((s) => s.id === section).map((s) => (
              <div key={s.id}>
                <SectionHead title={s.title} text={s.description} />
                {s.groups.map((g) => (
                  <Group key={g.title} title={g.title}>
                    {g.fields.filter((f) => f.key in values).map((f) => (
                      <FieldRow key={f.key} field={f} value={value(f.key)} restart={settings?.tiers[f.key] === "restart"}
                                changed={f.key in draft} onChange={(v) => set(f.key, v)} />
                    ))}
                  </Group>
                ))}
                {s.id === "storage" && <OtherKeys values={values} value={value} set={set} tiers={settings?.tiers ?? {}} />}
              </div>
            ))}
            {!q && section === "extensions" && <ExtensionsSection />}
            {!q && section === "conversations" && <ConversationsSection />}
            {!q && section === "shortcuts" && <ShortcutsSection />}
          </div>
        </div>

        {(dirty || saved) && (
          <div className="flex items-center justify-end gap-2 border-t bg-background/95 px-6 py-3 backdrop-blur">
            {saved && !dirty && <span className="mr-auto text-xs text-muted-foreground">Saved. Applies from the next message.</span>}
            {dirty && <span className="mr-auto text-xs text-muted-foreground">{Object.keys(draft).length} unsaved change(s)</span>}
            {dirty && <Button variant="ghost" onClick={() => setDraft({})}><RotateCcw className="h-3.5 w-3.5" />Reset</Button>}
            {dirty && <Button onClick={() => void save()}>Save</Button>}
          </div>
        )}
      </div>
    </div>
  )
}

function SectionHead({ title, text }: { title: string; text: string }) {
  return (
    <div className="mb-2 mt-2">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{text}</p>
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="divide-y rounded-xl border bg-card">{children}</div>
    </section>
  )
}

function Row({ label, help, children, badge, wide }: {
  label: string; help?: string; children: React.ReactNode; badge?: React.ReactNode; wide?: boolean
}) {
  return (
    <div className={cn("flex gap-4 px-4 py-3", wide ? "flex-col" : "items-center")}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-medium">{label}{badge}</div>
        {help && <p className="mt-0.5 text-xs text-muted-foreground">{help}</p>}
      </div>
      <div className={cn(wide ? "w-full" : "shrink-0")}>{children}</div>
    </div>
  )
}

const inputClass = "h-8 rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring/30"

function FieldRow({ field, value, restart, changed, onChange }: {
  field: Field; value: unknown; restart: boolean; changed: boolean; onChange: (v: unknown) => void
}) {
  const c = field.control
  const badge = (
    <>
      {restart && <span className="rounded bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-700 dark:text-amber-400">restart</span>}
      {changed && <span className="h-1.5 w-1.5 rounded-full bg-primary" title="Unsaved" />}
    </>
  )
  const wide = c.type === "textarea" || c.type === "list" || (c.type === "text" && String(value ?? "").length > 24)
  let control: React.ReactNode
  switch (c.type) {
    case "toggle":
      control = <Switch checked={Boolean(value)} onChange={onChange} label={field.label} />
      break
    case "slider":
      control = (
        <div className="flex items-center gap-3">
          <input type="range" min={c.min} max={c.max} step={c.step} value={Number(value ?? 0)}
                 onChange={(e) => onChange(Number(e.target.value))} className="w-40 accent-primary" />
          <input type="number" min={c.min} max={c.max} step={c.step} value={Number(value ?? 0)}
                 onChange={(e) => onChange(Number(e.target.value))} className={cn(inputClass, "w-20 text-right font-mono")} />
        </div>
      )
      break
    case "number":
      control = <input type="number" min={c.min} max={c.max} step={c.step} value={Number(value ?? 0)}
                       onChange={(e) => onChange(Number(e.target.value))} className={cn(inputClass, "w-28 text-right font-mono")} />
      break
    case "select":
      control = (
        <select value={String(value)} onChange={(e) => onChange(e.target.value)} className={cn(inputClass, "w-40")}>
          {c.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      )
      break
    case "textarea":
      control = <textarea rows={c.rows ?? 4} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}
                          className="w-full rounded-md border bg-background p-2.5 font-mono text-xs leading-relaxed outline-none focus:ring-2 focus:ring-ring/30" />
      break
    case "model":
      control = <ModelSelect value={String(value ?? "")} onChange={onChange} />
      break
    case "list":
      control = <textarea rows={3} value={((value as string[]) ?? []).join("\n")}
                          onChange={(e) => onChange(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
                          className="w-full rounded-md border bg-background p-2.5 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/30" />
      break
    default: {
      // gpu_layers is "all" or a number; keep numbers numeric.
      control = <input value={String(value ?? "")} onChange={(e) => {
        const raw = e.target.value
        onChange(field.key === "model.gpu_layers" && /^\d+$/.test(raw) ? Number(raw) : raw)
      }} className={cn(inputClass, wide ? "w-full font-mono text-xs" : "w-56")} />
    }
  }
  return <Row label={field.label} help={field.help} badge={badge} wide={wide}>{control}</Row>
}

/** The models in the models folder, with the one llama-server is running marked. */
function ModelSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [list, setList] = useState<ModelList | null>(null)
  useEffect(() => {
    api.listModels().then(setList).catch(() => setList({ models: [], loaded: "", selected: "" }))
  }, [])
  const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`
  const names = list?.models.map((m) => m.name) ?? []
  return (
    <div className="flex flex-col items-end gap-1">
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cn(inputClass, "w-64")}>
        {!names.includes(value) && <option value={value}>{value || "(none)"} - not found</option>}
        {list?.models.map((m) => (
          <option key={m.name} value={m.name}>
            {m.name} ({gb(m.bytes)}{m.mmproj ? ", images" : ""}){m.name === list.loaded ? " - running" : ""}
          </option>
        ))}
      </select>
      {list && list.models.length === 0 && (
        <span className="text-[11px] text-muted-foreground">No models found. Put each model in its own folder under llm/.</span>
      )}
    </div>
  )
}

/** Backend keys the schema neither describes nor hides, so a new one is never unreachable. */
function OtherKeys({ values, value, set, tiers }: {
  values: Record<string, unknown>; value: (k: string) => unknown; set: (k: string, v: unknown) => void
  tiers: Record<string, string>
}) {
  const described = useMemo(() => describedKeys(), [])
  const rest = Object.keys(values).filter((k) => !described.has(k) && !HIDDEN.has(k)).sort()
  if (!rest.length) return null
  return (
    <Group title="Other">
      {rest.map((key) => {
        const v = values[key]
        const control = typeof v === "boolean" ? { type: "toggle" as const }
          : typeof v === "number" ? { type: "number" as const }
          : Array.isArray(v) ? { type: "list" as const } : { type: "text" as const }
        return <FieldRow key={key} field={{ key, label: key, control }} value={value(key)}
                         restart={tiers[key] === "restart"} changed={false} onChange={(nv) => set(key, nv)} />
      })}
    </Group>
  )
}

function GeneralSection() {
  const prefs = usePrefs()
  return (
    <div>
      <SectionHead title="General" text="How this browser shows Atlas. Stored in the browser, not in settings.json." />
      <Group title="Appearance">
        <Row label="Theme">
          <div className="flex rounded-lg border p-0.5">
            {(["system", "light", "dark"] as const).map((t) => (
              <button key={t} type="button" onClick={() => setPrefs({ theme: t })}
                      className={cn("flex items-center gap-1 rounded-md px-2.5 py-1 text-xs capitalize",
                                    prefs.theme === t ? "bg-accent font-medium" : "text-muted-foreground")}>
                {t === "system" && <Monitor className="h-3 w-3" />}{t}
              </button>
            ))}
          </div>
        </Row>
        <Row label="Show generation stats" help="Tokens, speed and time under each answer.">
          <Switch checked={prefs.showStats} onChange={(v) => setPrefs({ showStats: v })} />
        </Row>
        <Row label="Show context meter" help="How full the context window is, under the message box.">
          <Switch checked={prefs.showContextMeter} onChange={(v) => setPrefs({ showContextMeter: v })} />
        </Row>
        <Row label="Expand reasoning" help="Show the model's thinking open by default once it finishes.">
          <Switch checked={prefs.expandReasoning} onChange={(v) => setPrefs({ expandReasoning: v })} />
        </Row>
        <Row label="Expand tool calls" help="Show each tool's arguments and output open by default.">
          <Switch checked={prefs.expandTools} onChange={(v) => setPrefs({ expandTools: v })} />
        </Row>
      </Group>
      <Group title="Scrolling">
        <Row label="Auto-scroll while generating" help="Off: your message moves to the top and the answer grows below it, so you can read from the start. On: the view follows the newest text.">
          <Switch checked={prefs.autoScroll} onChange={(v) => setPrefs({ autoScroll: v })} />
        </Row>
      </Group>
      <Group title="Input">
        <Row label="Enter sends" help="Off: Enter adds a line and Ctrl+Enter sends.">
          <Switch checked={prefs.sendOnEnter} onChange={(v) => setPrefs({ sendOnEnter: v })} />
        </Row>
      </Group>
    </div>
  )
}

function ExtensionsSection() {
  const settings = useAtlas((s) => s.settings)
  return (
    <div>
      <SectionHead title="Skills & MCP" text="Switch what the agent can use. Install and configure on their own pages." />
      <Group title="Skills">
        {(settings?.skills ?? []).map((s) => (
          <Row key={s.folder} label={s.name} help={s.error ?? s.description}>
            <Switch checked={s.enabled} disabled={Boolean(s.error)} onChange={async (on) => {
              await api.toggleSkill(s.folder, on)
              await atlas.refreshSettings()
            }} />
          </Row>
        ))}
        <div className="px-4 py-2.5"><Link to="/skills" className="text-xs text-primary hover:underline">Manage skills →</Link></div>
      </Group>
      <Group title="MCP servers">
        {(settings?.mcp ?? []).length === 0 && <p className="px-4 py-3 text-xs text-muted-foreground">None configured.</p>}
        {(settings?.mcp ?? []).map((m) => (
          <Row key={m.name} label={m.name} help={`${m.transport} · ${m.status}${m.tools.length ? ` · ${m.tools.filter((t) => t.enabled).length}/${m.tools.length} tools` : ""}`}>
            <Switch checked={m.enabled} onChange={async (on) => {
              await api.toggleMcp(m.name, on)
              await atlas.refreshSettings()
            }} />
          </Row>
        ))}
        <div className="px-4 py-2.5"><Link to="/mcp" className="text-xs text-primary hover:underline">Manage MCP servers →</Link></div>
      </Group>
    </div>
  )
}

function ConversationsSection() {
  const chats = useAtlas((s) => s.chats)
  const [message, setMessage] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  return (
    <div>
      <SectionHead title="Conversations" text="Exports include every version and the model's history, so an imported chat can be continued." />
      <Group title="Import and export">
        <Row label="Export all conversations" help={`${chats.length} conversation(s) as one JSON file.`}>
          <Button variant="outline" disabled={!chats.length} onClick={async () => {
            downloadJson(`atlas-conversations-${new Date().toISOString().slice(0, 10)}.json`,
                         await atlas.exportChats(chats.map((c) => c.id)))
          }}><Download className="h-3.5 w-3.5" />Export</Button>
        </Row>
        <Row label="Import conversations" help="A file exported from Atlas: one conversation or many.">
          <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-3.5 text-sm font-medium hover:bg-accent">
            <Upload className="h-3.5 w-3.5" />Import
            <input type="file" accept="application/json,.json" hidden onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (!file) return
              try {
                const n = await atlas.importChats(JSON.parse(await file.text()))
                setMessage(`Imported ${n} conversation(s).`)
              } catch (err) {
                setMessage(`Import failed: ${err instanceof Error ? err.message : err}`)
              }
            }} />
          </label>
        </Row>
      </Group>
      {message && <Notice tone="info" onClose={() => setMessage(null)}>{message}</Notice>}
      <Group title="Danger zone">
        <Row label="Delete all conversations" help="Removes every chat, its snapshots and its uploaded files.">
          {confirm ? (
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
              <Button variant="destructive" onClick={async () => { await atlas.deleteAllChats(); setConfirm(false) }}>
                Delete {chats.length}
              </Button>
            </div>
          ) : (
            <Button variant="outline" className="text-destructive" disabled={!chats.length} onClick={() => setConfirm(true)}>
              <MessagesSquare className="h-3.5 w-3.5" />Delete all
            </Button>
          )}
        </Row>
      </Group>
    </div>
  )
}

function ShortcutsSection() {
  return (
    <div>
      <SectionHead title="Shortcuts" text="Work anywhere in the app. On macOS, Ctrl is Cmd." />
      <Group title="Keyboard">
        {SHORTCUTS.map((s) => (
          <Row key={s.label} label={s.label}>
            <span className="flex items-center gap-1">
              <Keyboard className="mr-1 h-3.5 w-3.5 text-muted-foreground" />
              {s.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}
            </span>
          </Row>
        ))}
      </Group>
    </div>
  )
}

function SettingsSearch({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative mt-2">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onChange("")}
        placeholder="Search settings"
        className="h-8 w-full rounded-md border border-border/50 bg-background pl-8 pr-7 text-sm outline-none focus:border-border"
      />
      {value && (
        <button type="button" onClick={() => onChange("")} aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
