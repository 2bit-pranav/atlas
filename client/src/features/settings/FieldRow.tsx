import { useEffect, useMemo, useState } from "react"
import * as api from "@/api/client"
import { HIDDEN, describedKeys, type Field } from "@/features/settings/schema"
import { Switch } from "@/components/ui/Switch"
import type { ModelList } from "@/api/types"
import { cn } from "@/lib/cn"
import { Group, Row } from "@/features/settings/layout"

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
