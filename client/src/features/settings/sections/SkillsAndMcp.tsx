import { Link } from "react-router-dom"
import * as api from "@/api/client"
import { atlas, useAtlas } from "@/state/store"
import { Switch } from "@/components/ui/Switch"
import { Group, Row, SectionHead } from "@/features/settings/layout"

export function ExtensionsSection() {
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
