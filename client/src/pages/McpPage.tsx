/**
 * MCP servers: connect, switch tools on and off, and find new servers.
 *
 * Every tool schema is sent with every request, which on a 32k window and a 2B
 * model is the real cost of MCP -- so token estimates are shown per tool, per
 * server, and against the context window, and tools can be switched off
 * individually rather than only by server.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import {
  ChevronDown, Cloud, HardDrive, Loader2, Plug, Plus, RefreshCw, Search, Trash2,
} from "lucide-react"

import * as api from "@/lib/api"
import type { McpServer, RegistryOption, RegistryServer } from "@/lib/types"
import { useAtlas } from "@/lib/store"
import { Button, Empty, Notice, PageShell, Switch } from "@/components/ui/kit"
import { cn } from "@/lib/utils"

export function McpPage() {
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<{ name: string; config: string; env?: RegistryOption["env"] } | null>(null)
  const contextSize = Number(useAtlas((s) => s.settings?.values["model.context_size"]) ?? 32768)

  const run = async (fn: () => Promise<McpServer[]>) => {
    setError(null)
    try {
      setServers(await fn())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const latest = useRef<McpServer[] | null>(null)
  useEffect(() => {
    latest.current = servers
  }, [servers])
  useEffect(() => {
    void run(api.listMcp)
    // A server may still be connecting when the page opens: look again shortly.
    const timer = setInterval(() => {
      if (latest.current?.some((s) => s.status === "connecting")) void run(api.listMcp)
    }, 2000)
    return () => clearInterval(timer)
  }, [])

  const totalTokens = (servers ?? []).filter((s) => s.status === "connected").reduce((n, s) => n + s.tokens, 0)
  const share = totalTokens / contextSize

  return (
    <PageShell
      title="MCP servers"
      description="Model Context Protocol servers add tools to the agent. Local servers run on this machine; remote ones send what the agent passes them to another computer."
      actions={<Button onClick={() => setDraft({ name: "", config: '{\n  "command": "npx",\n  "args": ["-y", "package-name"]\n}' })}><Plus className="h-4 w-4" />Add server</Button>}
    >
      <div className="rounded-xl border bg-card p-4">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">Tool schemas in every request</span>
          <span className={cn("font-mono", share > 0.15 ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground")}>
            ~{totalTokens.toLocaleString()} tokens · {(share * 100).toFixed(1)}% of {contextSize.toLocaleString()}
          </span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full", share > 0.15 ? "bg-amber-500" : "bg-primary")}
               style={{ width: `${Math.min(100, share * 100)}%` }} />
        </div>
        {share > 0.15 && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            A small model picks tools less reliably as the list grows. Switch off tools you do not need.
          </p>
        )}
      </div>

      {error && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}

      {draft && (
        <ServerForm
          key={draft.name + draft.config}
          draft={draft}
          onCancel={() => setDraft(null)}
          onSave={async (name, config) => {
            await run(() => api.upsertMcp(name, config))
            setDraft(null)
          }}
          onError={setError}
        />
      )}

      <h2 className="mt-8 text-sm font-semibold">Configured</h2>
      {servers === null ? (
        <div className="mt-6 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : servers.length === 0 ? (
        <Empty icon={Plug} title="No MCP servers" text="Add one by hand, or search the registry below." />
      ) : (
        <div className="mt-3 space-y-3">
          {servers.map((s) => (
            <ServerCard
              key={s.name}
              server={s}
              onToggle={(on) => run(() => api.toggleMcp(s.name, on))}
              onReconnect={() => run(() => api.reconnectMcp(s.name))}
              onDelete={() => run(() => api.deleteMcp(s.name))}
              onTool={(tool, on) => run(() => api.toggleMcpTool(s.name, tool, on))}
              onEdit={() => setDraft({ name: s.name, config: JSON.stringify(s.config, null, 2) })}
            />
          ))}
        </div>
      )}

      <Registry onPick={(server, option) => setDraft({
        name: server.title.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-|-$/g, ""),
        config: JSON.stringify(option.config, null, 2),
        env: option.env,
      })} />
    </PageShell>
  )
}

function StatusDot({ status }: { status: McpServer["status"] }) {
  const color = {
    connected: "bg-emerald-500", connecting: "bg-amber-500 animate-pulse", failed: "bg-destructive",
    stopped: "bg-muted-foreground", disabled: "bg-muted-foreground/40",
  }[status]
  return <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", color)} title={status} />
}

function ServerCard({ server, onToggle, onReconnect, onDelete, onTool, onEdit }: {
  server: McpServer
  onToggle: (on: boolean) => void
  onReconnect: () => void
  onDelete: () => void
  onTool: (tool: string, on: boolean) => void
  onEdit: () => void
}) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const command = server.config.url ? String(server.config.url)
    : [server.config.command, ...((server.config.args as string[] | undefined) ?? [])].join(" ")
  const enabledTools = server.tools.filter((t) => t.enabled).length

  return (
    <div className="rounded-xl border bg-card">
      <div className="flex items-center gap-3 p-4">
        <StatusDot status={server.status} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{server.name}</span>
            <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium",
              server.transport === "remote" ? "bg-amber-500/15 text-amber-700 dark:text-amber-400" : "bg-muted text-muted-foreground")}>
              {server.transport === "remote" ? <Cloud className="h-3 w-3" /> : <HardDrive className="h-3 w-3" />}
              {server.transport === "remote" ? "remote · leaves this machine" : "local"}
            </span>
          </div>
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground" title={command}>{command}</p>
        </div>
        {server.status === "connected" && (
          <span className="hidden text-[11px] text-muted-foreground sm:inline">
            {enabledTools}/{server.tools.length} tools · ~{server.tokens.toLocaleString()} tok
          </span>
        )}
        <Button size="icon-sm" variant="ghost" title="Reconnect" onClick={onReconnect} disabled={!server.enabled}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
        <Switch checked={server.enabled} onChange={onToggle} label={`Enable ${server.name}`} />
      </div>

      {server.error && <p className="border-t px-4 py-2 font-mono text-[11px] text-destructive">{server.error}</p>}

      <div className="flex items-center gap-1 border-t px-2 py-1.5">
        <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)} disabled={!server.tools.length}>
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
          Tools
        </Button>
        <Button size="sm" variant="ghost" onClick={onEdit}>Edit</Button>
        <span className="flex-1" />
        {confirm ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button size="sm" variant="destructive" onClick={onDelete}>Remove</Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}><Trash2 className="h-3.5 w-3.5" /></Button>
        )}
      </div>

      {open && (
        <div className="divide-y border-t">
          {server.tools.map((tool) => (
            <div key={tool.name} className="flex items-start gap-3 px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="font-mono text-xs">{tool.agent_name}</p>
                <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{tool.description}</p>
              </div>
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground">~{tool.tokens} tok</span>
              <Switch checked={tool.enabled} onChange={(on) => onTool(tool.name, on)} label={`Enable ${tool.name}`} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Accepts a bare server config, `{name: config}`, or a full `{"mcpServers": {...}}` block. */
function parseConfig(name: string, text: string): { name: string; config: Record<string, unknown> }[] {
  const data = JSON.parse(text) as Record<string, unknown>
  if (data.command || data.url) return [{ name, config: data }]
  const servers = (data.mcpServers ?? data) as Record<string, Record<string, unknown>>
  return Object.entries(servers).map(([n, config]) => ({ name: n, config }))
}

function ServerForm({ draft, onCancel, onSave, onError }: {
  draft: { name: string; config: string; env?: RegistryOption["env"] }
  onCancel: () => void
  onSave: (name: string, config: Record<string, unknown>) => Promise<void>
  onError: (message: string) => void
}) {
  const [name, setName] = useState(draft.name)
  const [config, setConfig] = useState(draft.config)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    let entries
    try {
      entries = parseConfig(name.trim(), config)
    } catch (e) {
      return onError(`Not valid JSON: ${e instanceof Error ? e.message : e}`)
    }
    if (entries.some((e) => !e.name)) return onError("Give the server a name.")
    setBusy(true)
    for (const entry of entries) await onSave(entry.name, entry.config)
    setBusy(false)
  }

  return (
    <div className="mt-4 rounded-xl border bg-card p-4">
      <p className="text-sm font-medium">{draft.name ? `Server: ${draft.name}` : "New server"}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Paste the JSON from the server's README. A whole <span className="font-mono">mcpServers</span> block adds every server in it.
      </p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="name"
        className="mt-3 h-9 w-full rounded-lg border bg-background px-3 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/30"
      />
      <textarea
        value={config}
        onChange={(e) => setConfig(e.target.value)}
        rows={8}
        spellCheck={false}
        className="mt-2 w-full rounded-lg border bg-background p-3 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/30"
      />
      {draft.env && draft.env.length > 0 && (
        <div className="mt-2 rounded-lg bg-muted/40 p-2.5 text-[11px]">
          <p className="font-medium">Environment this server reads. Fill the values into <span className="font-mono">env</span> above:</p>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {draft.env.map((e) => (
              <li key={e.name}>
                <span className="font-mono text-foreground">{e.name}</span>
                {e.isRequired && <span className="text-destructive"> required</span>}
                {e.isSecret && <span> · secret</span>}
                {e.description && <span> - {e.description}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button onClick={() => void save()} disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}Save and connect
        </Button>
      </div>
    </div>
  )
}

function Registry({ onPick }: { onPick: (server: RegistryServer, option: RegistryOption) => void }) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<RegistryServer[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const search = async () => {
    setBusy(true)
    setError(null)
    try {
      setResults(await api.searchRegistry(query))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const sorted = useMemo(() => results ?? [], [results])

  return (
    <div className="mt-10">
      <h2 className="text-sm font-semibold">Find servers</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Searches the official MCP registry. It can take up to half a minute to answer.
      </p>
      <div className="mt-3 flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void search()}
            placeholder="filesystem, git, sqlite, browser..."
            className="h-9 w-full rounded-lg border bg-background pl-8 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring/30"
          />
        </div>
        <Button onClick={() => void search()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}Search
        </Button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {results && results.length === 0 && <p className="mt-4 text-xs text-muted-foreground">Nothing found.</p>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {sorted.map((server) => (
          <div key={server.name} className="flex flex-col rounded-xl border bg-card p-3.5">
            <div className="flex items-baseline gap-2">
              <span className="truncate text-sm font-medium">{server.title}</span>
              {server.version && <span className="font-mono text-[10px] text-muted-foreground">v{server.version}</span>}
            </div>
            <p className="truncate font-mono text-[10px] text-muted-foreground">{server.name}</p>
            <p className="mt-1.5 line-clamp-3 text-xs text-muted-foreground">{server.description}</p>
            <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
              {server.options.map((option, i) => (
                <Button key={i} size="sm" variant="outline" onClick={() => onPick(server, option)}>
                  {option.local ? <HardDrive className="h-3 w-3" /> : <Cloud className="h-3 w-3" />}
                  {option.local ? `Add (${option.kind})` : "Add remote"}
                </Button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default McpPage
