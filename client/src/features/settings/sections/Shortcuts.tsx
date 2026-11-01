import { Keyboard } from "lucide-react"
import { SHORTCUTS } from "@/lib/shortcuts"
import { Kbd } from "@/components/ui/Kbd"
import { Group, Row, SectionHead } from "@/features/settings/layout"

export function ShortcutsSection() {
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
