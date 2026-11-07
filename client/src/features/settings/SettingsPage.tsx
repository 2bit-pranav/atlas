import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { RotateCcw, Search, X } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import { usePrefs } from "@/state/prefs"
import { SECTIONS } from "@/features/settings/schema"
import { Button } from "@/components/ui/Button"
import { Notice } from "@/components/ui/Notice"
import { cn } from "@/lib/cn"
import { Group, SectionHead } from "@/features/settings/layout"
import { FieldRow, OtherKeys } from "@/features/settings/FieldRow"
import { GeneralSection } from "@/features/settings/sections/General"
import { ConversationsSection } from "@/features/settings/sections/Conversations"
import { ShortcutsSection } from "@/features/settings/sections/Shortcuts"

const navItem = (id: string) => ({ id, title: SECTIONS.find((s) => s.id === id)?.title ?? id })
/** Most-used first: what changes results, then the model; tuning under Advanced, in developer mode only. */
const NAV = [
  { id: "general", title: "General" },
  navItem("agent"),
  navItem("access"),
  navItem("model"),
  { id: "conversations", title: "Conversations" },
  { id: "shortcuts", title: "Shortcuts" },
]
const ADVANCED = SECTIONS.filter((s) => s.advanced).map((s) => ({ id: s.id, title: s.title }))

export function SettingsPage() {
  const { section = "general" } = useParams()
  const navigate = useNavigate()
  const { devMode } = usePrefs()
  const advanced = devMode ? ADVANCED : []
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
  const matches = useMemo(() => !q ? [] : SECTIONS.filter((s) => devMode || !s.advanced).flatMap((s) => s.groups.flatMap((g) =>
    g.fields.filter((f) => f.key in values &&
      [f.label, f.help ?? "", f.key, g.title].some((t) => t.toLowerCase().includes(q)))
      .map((f) => ({ field: f, where: `${s.title} · ${g.title}` })))), [q, values, devMode])

  return (
    <div className="flex h-full min-h-0">
      <nav className="hidden w-48 shrink-0 border-r px-3 py-6 md:block">
        <Link to="/" className="px-2 text-xs text-muted-foreground hover:text-foreground">← Back to chat</Link>
        <p className="mt-4 px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Settings</p>
        <SettingsSearch value={query} onChange={setQuery} />
        {[{ title: "", items: NAV }, { title: "Advanced", items: advanced }].filter((l) => l.items.length).map((list) => (
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
              {devMode && (
                <optgroup label="Advanced">
                  {ADVANCED.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
                </optgroup>
              )}
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
            {!q && SECTIONS.filter((s) => s.id === section && (devMode || !s.advanced)).map((s) => (
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
