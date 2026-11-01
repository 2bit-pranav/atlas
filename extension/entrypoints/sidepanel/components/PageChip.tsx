/** Which page the chat is attached to, under the header. */

import { Globe, ShieldOff } from "lucide-react"
import { cn } from "@/lib/cn"
import { type TabInfo } from "@ext/shared/tab"
import { host } from "../url"

/** What Atlas can see: the attached page, or why it cannot read it. */
export function PageChip({ tab, blocked: reason, pdf }: { tab: TabInfo | null; blocked: string | null; pdf: boolean }) {
  let host = ""
  try {
    host = tab ? new URL(tab.url).hostname : ""
  } catch {
    host = ""
  }
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2" title={tab?.url}>
      {reason ? <ShieldOff className="h-4 w-4 shrink-0 text-muted-foreground" />
        : tab?.favIconUrl ? <img src={tab.favIconUrl} alt="" className="h-4 w-4 shrink-0" />
        : <Globe className="h-4 w-4 shrink-0 text-muted-foreground" />}
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{tab?.title || "No page"}</p>
        <p className={cn("truncate text-[11px]", reason ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
          {reason ? `Not read: ${reason}` : pdf ? `PDF · read as a file${host ? ` · ${host}` : ""}`
            : tab?.viewer ? `PDF in the Atlas viewer${host ? ` · ${host}` : " · on this computer"}` : `Atlas can read this page · ${host}`}
        </p>
      </div>
    </div>
  )
}
