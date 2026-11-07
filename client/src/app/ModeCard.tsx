/**
 * The sidebar's footer: the running model and the access mode. Mode is
 * global and read when each message starts, so a switch never changes a task
 * already running. Raising it to Work asks first; lowering never does.
 */

import { useState } from "react"
import * as Dropdown from "@radix-ui/react-dropdown-menu"
import { Check, ChevronsUpDown } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import { cn } from "@/lib/cn"

type Mode = "look" | "ask" | "work"

const MODES: { id: Mode; label: string; text: string }[] = [
  { id: "look", label: "Look", text: "Reads only. Nothing is changed." },
  { id: "ask", label: "Ask", text: "Asks before changing, deleting or running anything." },
  { id: "work", label: "Work", text: "Changes your folders without asking. Deleting still asks." },
]

export function ModeCard() {
  const model = useAtlas((s) => String(s.settings?.values["model.name"] ?? ""))
  const mode = useAtlas((s) => (s.settings?.values["access.mode"] ?? "ask") as Mode)
  const [confirming, setConfirming] = useState(false)
  const set = (next: Mode) => void atlas.saveSettings({ "access.mode": next })
  const current = MODES.find((m) => m.id === mode) ?? MODES[1]

  return (
    <div className="shrink-0 border-t px-3 py-3 text-xs">
      <div className="flex items-center justify-between gap-2 px-1">
        <span className="text-muted-foreground">Model</span>
        <span className="truncate font-medium" title={model}>{model || "none"}</span>
      </div>
      <Dropdown.Root onOpenChange={(open) => !open && setConfirming(false)}>
        <Dropdown.Trigger asChild>
          <button type="button" aria-label={`Mode: ${current.label}`}
                  className="mt-1.5 flex w-full items-center justify-between gap-2 rounded-lg px-1 py-1 hover:bg-accent">
            <span className="text-muted-foreground">Mode</span>
            <span className={cn("flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium",
                                mode === "work" ? "bg-ask/15 text-ask" : "bg-muted")}>
              {current.label}<ChevronsUpDown className="h-3 w-3 opacity-60" />
            </span>
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content side="top" align="end" sideOffset={6}
                            className="z-50 w-64 rounded-lg border bg-popover p-1 text-sm text-popover-foreground shadow-md">
            {confirming ? (
              <div className="space-y-2 p-2">
                <p className="text-xs">In Work, changes and commands in your folders run without asking. Deleting still asks.</p>
                <div className="flex gap-2">
                  <Dropdown.Item onSelect={() => set("work")}
                                 className="cursor-pointer rounded-md border border-primary bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground outline-none">
                    Switch to Work
                  </Dropdown.Item>
                  <Dropdown.Item onSelect={() => setConfirming(false)}
                                 className="cursor-pointer rounded-md border px-2.5 py-1 text-xs font-medium outline-none data-[highlighted]:bg-accent">
                    Cancel
                  </Dropdown.Item>
                </div>
              </div>
            ) : (
              <>
                {MODES.map((m) => (
                  <Dropdown.Item key={m.id}
                                 onSelect={(e) => {
                                   if (m.id === "work" && mode !== "work") { e.preventDefault(); setConfirming(true) }
                                   else if (m.id !== mode) set(m.id)
                                 }}
                                 className="flex cursor-pointer gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-accent">
                    <Check className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", m.id !== mode && "invisible")} />
                    <span>
                      <span className="block font-medium">{m.label}</span>
                      <span className="block text-xs text-muted-foreground">{m.text}</span>
                    </span>
                  </Dropdown.Item>
                ))}
                <p className="px-2 pb-1 pt-1.5 text-[11px] text-muted-foreground">Applies from your next message.</p>
              </>
            )}
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
    </div>
  )
}
