/**
 * The @ menu: point the agent at a file, a skill, a tool or an MCP server.
 *
 * Files are this chat's workspace only (uploads and what the agent made).
 * Everything is inserted as text -- `@name`, or `@"a name"` when it has
 * spaces -- and the backend turns each known name into an explicit
 * instruction for the model (a file's path and how to read it),
 * which a 2B model needs -- it otherwise reaches for whichever tool looks
 * closest, the built-in one included.
 */

import { useEffect, useMemo, useRef, useState } from "react"
import { FileText, Plug, Sparkles, Wrench } from "lucide-react"

import * as api from "@/lib/api"
import { useAtlas } from "@/lib/store"
import type { ChatFile, WorkspaceFile } from "@/lib/types"
import { cn } from "@/lib/utils"

export type Mention =
  | { kind: "file"; name: string; file: ChatFile }
  | { kind: "skill" | "tool" | "server"; name: string; detail: string }

const GROUPS: { kind: Mention["kind"]; title: string; icon: typeof Wrench }[] = [
  { kind: "file", title: "Files", icon: FileText },
  { kind: "skill", title: "Skills", icon: Sparkles },
  { kind: "tool", title: "Tools", icon: Wrench },
  { kind: "server", title: "MCP servers", icon: Plug },
]

/** Everything that can be mentioned right now, for this chat. */
export function useMentionables(chatId: string | null, active: boolean): Mention[] {
  const settings = useAtlas((s) => s.settings)
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  useEffect(() => {
    if (!active || !chatId) return
    api.listWorkspace(chatId).then(setFiles).catch(() => setFiles([]))
  }, [active, chatId])

  return useMemo(() => {
    const out: Mention[] = []
    for (const f of files)
      out.push({ kind: "file", name: f.name,
                 file: { name: f.name, path: (f as WorkspaceFile & { path: string }).path, size: f.size, type: f.type } })
    for (const s of settings?.skills ?? [])
      if (s.enabled) out.push({ kind: "skill", name: s.folder, detail: s.description })
    const tools = [...(settings?.tools.builtin_tools ?? [])]
    if (settings?.values["tools.documents"] !== false) tools.push("create_document", "edit_document")
    for (const t of tools) out.push({ kind: "tool", name: t, detail: "built in" })
    for (const m of settings?.mcp ?? []) {
      if (m.status !== "connected") continue
      out.push({ kind: "server", name: m.name, detail: `${m.tools.filter((t) => t.enabled).length} tools` })
      for (const t of m.tools) if (t.enabled) out.push({ kind: "tool", name: t.agent_name, detail: `MCP: ${m.name}` })
    }
    return out
  }, [files, settings])
}

export function MentionMenu({ items, query, index, onPick, onHover }: {
  items: Mention[]
  query: string
  index: number
  onPick: (m: Mention) => void
  onHover: (i: number) => void
}) {
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    list.current?.querySelector(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" })
  }, [index])

  if (!items.length) {
    return (
      <div className="absolute bottom-full left-0 z-40 mb-2 w-80 rounded-xl border bg-popover p-3 text-xs text-muted-foreground shadow-lg">
        Nothing matches "@{query}".
      </div>
    )
  }
  return (
    <div ref={list} className="absolute bottom-full left-0 z-40 mb-2 max-h-72 w-80 overflow-y-auto rounded-xl border bg-popover p-1 text-sm shadow-lg">
      {GROUPS.map((g) => {
        const group = items.filter((m) => m.kind === g.kind)
        if (!group.length) return null
        return (
          <div key={g.kind}>
            <p className="px-2 pb-1 pt-2 text-[11px] uppercase tracking-wide text-muted-foreground/70">{g.title}</p>
            {group.map((m) => {
              // `items` is already in menu order, so its index is the row's.
              const i = items.indexOf(m)
              return (
                <button key={`${m.kind}:${m.name}`} type="button" data-index={i}
                        onMouseDown={(e) => { e.preventDefault(); onPick(m) }}
                        onMouseEnter={() => onHover(i)}
                        className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left", i === index && "bg-accent")}>
                  <g.icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate font-mono text-xs">{m.name}</span>
                  <span className="ml-auto max-w-32 shrink-0 truncate text-[11px] text-muted-foreground">
                    {m.kind === "file" ? "file" : m.detail}
                  </span>
                </button>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

/** Filter, ordered like the menu shows them, at most 8 per group. */
export function filterMentions(all: Mention[], query: string): Mention[] {
  const q = query.toLowerCase()
  return GROUPS.flatMap((g) =>
    all.filter((m) => m.kind === g.kind && m.name.toLowerCase().includes(q))
       .sort((a, b) => Number(!a.name.toLowerCase().startsWith(q)) - Number(!b.name.toLowerCase().startsWith(q)))
       .slice(0, 8))
}
