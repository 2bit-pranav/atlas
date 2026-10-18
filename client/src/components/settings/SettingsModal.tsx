/**
 * Settings, edited against what the backend actually serves.
 *
 * This is a generic renderer, not a hand-written form per setting. The backend
 * already returns every leaf as a flat dotted key with a tier attached, so the
 * honest thing to do is walk that map and render a control for whatever type
 * each value turns out to be. Adding a setting to `settings.json` then makes it
 * appear here with no frontend change at all -- which is the point of the
 * dotted-key design in the first place.
 *
 * Three rules the UI has to honour:
 *
 * 1. **RESTART keys are shown, not hidden.** They are disabled with the reason
 *    on them, because a setting you cannot find is worse than one you can see
 *    but cannot reach.
 * 2. **Only changed keys are sent.** `PUT /settings` rejects the entire request
 *    with a 409 if a single RESTART key appears in the patch, so resending the
 *    whole form would guarantee a 409.
 * 3. **Memory is locked, visibly.** The backend refuses `memory.enabled: true`
 *    and gives a reason; that reason is shown rather than swallowed.
 */

import React from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { AlertTriangle, Brain, Cpu, RotateCcw, Wrench } from "lucide-react"
import type { SettingsView } from "@/types/api"
import { cn } from "@/lib/utils"

interface SettingsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  settings: SettingsView | null
  onSave: (patch: Record<string, unknown>) => Promise<boolean>
  onRefresh: () => void
}

/** Human labels for the top-level groups, so the sidebar reads as prose. */
const GROUP_LABELS: Record<string, string> = {
  model: "Model",
  ports: "Ports",
  paths: "Paths",
  sampling: "Sampling",
  agent: "Agent",
  tools: "Tools",
  memory: "Memory",
  skills: "Skills",
  regeneration: "Regeneration",
  context: "Context",
}

/** Keys the backend refuses on principle, with the reason it gives. */
const LOCKED: Record<string, string> = {}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  open,
  onOpenChange,
  settings,
  onSave,
  onRefresh,
}) => {
  const [draft, setDraft] = React.useState<Record<string, unknown>>({})
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // Re-seed from the server whenever the modal opens. Seeding on every render
  // would throw away in-progress edits the moment a background refresh lands.
  React.useEffect(() => {
    if (open && settings) {
      setDraft({ ...settings.values })
      setError(null)
    }
  }, [open, settings])

  if (!settings) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base">Settings</DialogTitle>
            <DialogDescription className="text-xs">
              Waiting for the backend. Start it with <code>python -m agent</code>.
            </DialogDescription>
          </DialogHeader>
          <Button size="sm" variant="outline" onClick={onRefresh}>
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
            Retry
          </Button>
        </DialogContent>
      </Dialog>
    )
  }

  const tier = (key: string) => settings.tiers[key] ?? "live"
  const isRestart = (key: string) => tier(key) === "restart"

  /** Only keys whose value actually changed, which is what keeps 409s away. */
  const patch = (): Record<string, unknown> => {
    const out: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(draft)) {
      if (JSON.stringify(settings.values[key]) !== JSON.stringify(value)) {
        out[key] = value
      }
    }
    return out
  }

  const changedCount = Object.keys(patch()).length

  const handleSave = async () => {
    const body = patch()
    if (!Object.keys(body).length) {
      onOpenChange(false)
      return
    }
    setSaving(true)
    setError(null)
    const ok = await onSave(body)
    setSaving(false)
    if (ok) onOpenChange(false)
    else
      setError(
        "The backend rejected that change. Nothing was written; fix the field and try again.",
      )
  }

  const pending = Object.keys(settings.pending_restart)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl sm:max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <Cpu className="h-4 w-4 text-primary" />
            <span>Atlas Settings</span>
          </DialogTitle>
          <DialogDescription className="text-xs">
            Read from <code>settings.json</code> and written back to it. Keys marked
            restart need the backend relaunched before they take effect.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-5 py-2 pr-1 text-xs">
          {pending.length > 0 && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-2.5">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              <div>
                <p className="font-medium text-amber-600 dark:text-amber-400">
                  {pending.length} setting{pending.length > 1 ? "s" : ""} need a
                  restart
                </p>
                <p className="font-mono text-[11px] text-muted-foreground">
                  {pending.join(", ")}
                </p>
              </div>
            </div>
          )}

          {groupKeys(settings.values).map(([group, keys]) => (
            <section key={group} className="space-y-1.5">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {GROUP_LABELS[group] ?? group}
              </h3>
              <div className="space-y-1 rounded-xl border border-border/60 bg-muted/20 p-2">
                {keys.map((key) => (
                  <SettingRow
                    key={key}
                    settingKey={key}
                    value={draft[key] ?? settings.values[key]}
                    serverValue={settings.values[key]}
                    restart={isRestart(key)}
                    pendingRestart={
                      pending.includes(key) && settings.pending_restart[key] !== undefined
                    }
                    lockedReason={LOCKED[key]}
                    onChange={(next) =>
                      setDraft((prev) => ({ ...prev, [key]: next }))
                    }
                  />
                ))}
              </div>
            </section>
          ))}

          {/* Memory is not a setting: the backend refuses to enable it, and the
              reason is worth reading before anyone asks why. */}
          <section className="space-y-1.5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <Brain className="h-3.5 w-3.5" />
              Memory
            </h3>
            <div className="rounded-xl border border-border/60 bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-mono">memory.enabled</span>
                <span
                  className={cn(
                    "font-mono px-2 py-0.5 rounded",
                    settings.memory.enabled
                      ? "bg-emerald-500/15 text-emerald-600"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {String(settings.memory.enabled)}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {settings.memory.reason}
              </p>
            </div>
          </section>

          {settings.skills.length > 0 && (
            <section className="space-y-1.5">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
                <Wrench className="h-3.5 w-3.5" />
                Skills
              </h3>
              <div className="space-y-1 rounded-xl border border-border/60 bg-muted/20 p-2">
                {settings.skills.map((skill) => (
                  <div key={skill.name} className="p-1.5">
                    <p className="font-medium font-mono">{skill.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {skill.description}
                    </p>
                    {skill.scripts.length > 0 && (
                      <p className="font-mono text-[10px] text-muted-foreground/80 mt-0.5">
                        {skill.scripts.join("  ")}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-1.5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Tool groups
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(settings.tools.groups).map(([group, on]) => (
                <span
                  key={group}
                  className={cn(
                    "font-mono px-2 py-0.5 rounded border",
                    on
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600"
                      : "border-border bg-muted/30 text-muted-foreground",
                  )}
                >
                  {group}
                </span>
              ))}
            </div>
            <p className="font-mono text-[10px] text-muted-foreground/80">
              {settings.tools.builtin_tools.join(", ")}
            </p>
          </section>

          {error && (
            <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-2 text-destructive">
              {error}
            </p>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving || !changedCount}>
            {saving ? "Saving…" : `Save${changedCount ? ` (${changedCount})` : ""}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------- row --

interface SettingRowProps {
  settingKey: string
  value: unknown
  serverValue: unknown
  restart: boolean
  pendingRestart: boolean
  lockedReason?: string
  onChange: (next: unknown) => void
}

const SettingRow: React.FC<SettingRowProps> = ({
  settingKey,
  value,
  restart,
  pendingRestart,
  lockedReason,
  onChange,
}) => {
  const label = settingKey.split(".").slice(1).join(".")
  const disabled = restart || Boolean(lockedReason)

  return (
    <div className="flex items-center justify-between gap-3 px-1.5 py-1">
      <div className="min-w-0">
        <p className="font-mono truncate">{label}</p>
        {(restart || lockedReason || pendingRestart) && (
          <p className="text-[10px] text-muted-foreground">
            {lockedReason ?? (restart ? "needs a backend restart" : "changed")}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {typeof value === "boolean" ? (
          <input
            type="checkbox"
            checked={Boolean(value)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 rounded accent-primary cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          />
        ) : typeof value === "number" ? (
          <input
            type="number"
            step="any"
            value={String(value)}
            disabled={disabled}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-28 rounded-lg border bg-background px-2 py-1 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-40 disabled:cursor-not-allowed"
          />
        ) : (
          <input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            className="w-56 rounded-lg border bg-background px-2 py-1 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-40 disabled:cursor-not-allowed"
          />
        )}
        {restart && (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-medium uppercase text-amber-600 dark:text-amber-400">
            restart
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- helpers --

/** Group flat dotted keys by their first segment, preserving backend order. */
function groupKeys(values: Record<string, unknown>): [string, string[]][] {
  const groups = new Map<string, string[]>()
  for (const key of Object.keys(values)) {
    const group = key.split(".")[0]
    if (!groups.has(group)) groups.set(group, [])
    groups.get(group)!.push(key)
  }
  return [...groups.entries()]
}