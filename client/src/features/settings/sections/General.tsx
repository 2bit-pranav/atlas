import { Monitor } from "lucide-react"
import { setPrefs, usePrefs } from "@/state/prefs"
import { Switch } from "@/components/ui/Switch"
import { cn } from "@/lib/cn"
import { Group, Row, SectionHead } from "@/features/settings/layout"

export function GeneralSection() {
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
      <Group title="Advanced">
        <Row label="Show advanced settings" help="Sampling, recovery and limits, llama-server and ports, the model overrides, and the extension's pairing token.">
          <Switch checked={prefs.devMode} onChange={(v) => setPrefs({ devMode: v })} />
        </Row>
      </Group>
    </div>
  )
}
