/**
 * A new task: what Atlas should do, a few starters, what it made lately, and
 * which folders it may use. The web app's empty chat (the extension keeps its
 * own greeting).
 */

import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { FileSpreadsheet, FileText, Globe, Search } from "lucide-react"
import * as api from "@/api/client"
import type { RecentOutput } from "@/api/types"
import { atlas, useAtlas } from "@/state/store"
import { Composer } from "@/features/composer/Composer"
import { timeAgo, useNow } from "@/lib/time"

/** Prefilled the way a person starts typing, to finish in their own words. */
const STARTERS = [
  { icon: Search, label: "Find a file", text: "find my " },
  { icon: FileText, label: "Summarise a PDF", text: "summarise this pdf in a few points" },
  { icon: FileSpreadsheet, label: "Make a spreadsheet", text: "make an excel sheet of " },
  { icon: Globe, label: "Look something up", text: "look up " },
]

const ext = (name: string) => (name.includes(".") ? name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE")
const base = (p: string) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p

export function TaskHome() {
  const navigate = useNavigate()
  const now = useNow()
  const folders = useAtlas((s) => s.settings?.values["access.folders"]) as string[] | undefined
  const [outputs, setOutputs] = useState<RecentOutput[]>([])
  useEffect(() => {
    api.listOutputs().then(setOutputs).catch(() => setOutputs([]))
  }, [])
  const names = (folders ?? []).filter((f) => f.trim()).map(base)

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-7 px-4 pb-16 pt-[12vh]">
      <div>
        <h1 className="text-balance font-display text-3xl font-semibold tracking-tight md:text-4xl">What should Atlas do?</h1>
        <p className="mt-2 text-muted-foreground md:text-[15px]">
          Work with your files and documents, or look something up. Describe the result you want.
        </p>
      </div>

      <Composer placeholder="Describe the result you want…" />

      <div className="-mt-2 flex flex-wrap gap-2">
        {STARTERS.map((s) => (
          <button key={s.label} type="button" onClick={() => atlas.prefillComposer(s.text)}
                  className="inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <s.icon className="h-4 w-4" />{s.label}
          </button>
        ))}
      </div>

      {outputs.length > 0 && (
        <section>
          <h2 className="mb-1 font-display text-sm font-semibold">Recently made</h2>
          <ul className="divide-y">
            {outputs.map((o) => (
              <li key={o.chat_id + o.name}>
                <button type="button" onClick={() => navigate(`/c/${o.chat_id}`)}
                        className="flex w-full items-center gap-3 py-2.5 text-left hover:opacity-80">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 font-mono text-[10px] font-semibold text-primary">{ext(o.name)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{o.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      from "{o.chat_title || "Untitled task"}" · {timeAgo(o.created_at, now)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-sm text-muted-foreground">
        {names.length
          ? <>Atlas can use {names.length > 3 ? `${names.slice(0, 3).join(", ")} and ${names.length - 3} more` : names.join(", ")}. It asks before changing or deleting anything. </>
          : <>Atlas can only use the files you attach. </>}
        <Link to="/settings" className="text-foreground underline underline-offset-2">{names.length ? "Change" : "Add folders"}</Link>
      </p>
    </div>
  )
}
