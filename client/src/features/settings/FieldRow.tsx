import { useEffect, useMemo, useState } from "react"
import * as api from "@/api/client"
import { HIDDEN, describedKeys, type Field } from "@/features/settings/schema"
import { Switch } from "@/components/ui/Switch"
import type { ModelCaps, ModelList } from "@/api/types"
import { cn } from "@/lib/cn"
import { Group, Row } from "@/features/settings/layout"
import { atlas, useAtlas } from "@/state/store"

const inputClass = "h-8 rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring/30"

export function FieldRow({ field, value, restart, changed, onChange }: {
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
    case "exaKey":
      control = <ExaKey />
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

/** The Exa key: typed once and saved on its own; only "set" or "not set" ever comes back. */
function ExaKey() {
  const isSet = useAtlas((s) => Boolean(s.settings?.web?.exa_key_set))
  const [draft, setDraft] = useState("")
  const save = async (key: string) => {
    try {
      await api.putExaKey(key)
      setDraft("")
      await atlas.refreshSettings()
    } catch (error) {
      atlas.fail(error)
    }
  }
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{isSet ? "Set" : "Not set"}</span>
      <input type="password" autoComplete="off" value={draft} placeholder={isSet ? "Replace key" : "Paste key"}
             onChange={(e) => setDraft(e.target.value)} className={cn(inputClass, "w-48 font-mono text-xs")} />
      <button type="button" disabled={!draft.trim()} onClick={() => void save(draft)}
              className="rounded-md border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50">Save</button>
      {isSet && <button type="button" onClick={() => void save("")}
                        className="rounded-md border px-2 py-1 text-xs hover:bg-accent">Remove</button>}
    </div>
  )
}

/** The models in the models folder, with the one llama-server is running marked. */
function ModelSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [list, setList] = useState<ModelList | null>(null)
  useEffect(() => {
    api.listModels().then(setList).catch(() => setList({ models: [], loaded: "", selected: "" }))
  }, [])
  const gb = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`
  const names = list?.models.map((m) => m.name) ?? []
  const picked = list?.models.find((m) => m.name === value)
  return (
    <div className="flex flex-col items-end gap-1">
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cn(inputClass, "w-64")}>
        {!names.includes(value) && <option value={value}>{value || "(none)"} - not found</option>}
        {list?.models.map((m) => (
          <option key={m.name} value={m.name}>
            {m.name} ({gb(m.bytes)}){m.name === list.loaded ? " - running" : ""}
          </option>
        ))}
      </select>
      {picked && <CapsLine caps={picked.caps} />}
      {list && list.models.length === 0 && (
        <span className="text-[11px] text-muted-foreground">No models found. Put each model in its own folder under llm/.</span>
      )}
    </div>
  )
}

/** What a model can do, read from its files: "Images · Audio · Thinking · up to 131k context". */
function CapsLine({ caps }: { caps: ModelCaps }) {
  const can = [caps.vision && "Images", caps.audio && "Audio", caps.thinking && "Thinking"].filter(Boolean)
  return (
    <span className="flex flex-wrap justify-end gap-1">
      {can.map((c) => <span key={String(c)} className="rounded bg-muted px-1.5 py-px text-[11px] font-medium">{c}</span>)}
      {!can.length && <span className="text-[11px] text-muted-foreground">Text only</span>}
      {caps.thinking === null && <span className="text-[11px] text-muted-foreground">thinking unknown</span>}
      {caps.context && <span className="text-[11px] text-muted-foreground">up to {Math.round(caps.context / 1024)}k context</span>}
    </span>
  )
}

/** Backend keys the schema neither describes nor hides, so a new one is never unreachable. */
export function OtherKeys({ values, value, set, tiers }: {
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
