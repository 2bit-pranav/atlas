/** The page the chat is about, under the header: what it is, and whether Atlas reads it. */

import { Eye, EyeOff, FileText, Globe, ShieldOff, TextCursorInput } from "lucide-react"
import { cn } from "@/lib/cn"
import { type TabInfo } from "@ext/shared/tab"
import { googleTarget } from "@ext/page/google"
import { isYouTubeVideo } from "@ext/page/youtube"
import { isGoogleForm } from "@ext/fill/gforms"

const APP: Record<string, string> = {
  document: "Google Doc", spreadsheets: "Google Sheet", presentation: "Google Slides", "drive-file": "Drive file",
}

export function PageCard({ tab, blocked, pdf, reading, compact, onReading, onFill, onViewer }: {
  tab: TabInfo | null
  blocked: string | null
  pdf: boolean
  reading: boolean
  /** Once a chat has started: one 36 px line, so the answer gets the room. */
  compact: boolean
  onReading: (on: boolean) => void
  onFill: () => void
  onViewer: () => void
}) {
  let host = ""
  try {
    host = tab ? new URL(tab.url).hostname.replace(/^www\./, "") : ""
  } catch {
    host = ""
  }
  const app = tab ? googleTarget(tab.url)?.app : undefined
  const video = isYouTubeVideo(tab?.url ?? "")
  // Forms can be filled; a Google file or a video has none.
  const fillable = !tab?.viewer && !app && !video
  const readable = Boolean(tab && !blocked)
  const where = app ? `${APP[app]} · ${host}` : video ? "YouTube video" : isGoogleForm(tab?.url ?? "") ? "Google Form" : pdf ? `PDF · ${host || "on this computer"}` : tab?.viewer ? "PDF in the Atlas viewer" : host

  const toggle = readable && (
    <button type="button" aria-pressed={reading} onClick={() => onReading(!reading)}
            title={reading ? "Atlas reads this page with each message. Click to stop." : "Messages are not about this page. Click to read it."}
            className={cn("flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-colors",
                          reading ? "bg-ok/10 text-ok hover:bg-ok/15" : "bg-muted text-muted-foreground hover:text-foreground")}>
      {reading ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
      {reading ? (compact ? "Reading" : "Can read") : "Not reading"}
    </button>
  )

  if (compact)
    return (
      <div className="flex h-9 shrink-0 items-center gap-2 border-b bg-muted/30 pl-3 pr-1.5" title={tab?.url}>
        {blocked ? <ShieldOff className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          : tab?.favIconUrl ? <img src={tab.favIconUrl} alt="" className="h-3.5 w-3.5 shrink-0" />
          : <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 flex-1 truncate text-[12.5px]">
          {tab?.title || "No page"} <span className="text-muted-foreground">· {blocked ? "never read" : where}</span>
        </span>
        {readable && reading && pdf && (
          <button type="button" onClick={onViewer} className="shrink-0 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">Open in viewer</button>
        )}
        {readable && reading && !pdf && fillable && (
          <button type="button" aria-label="Fill this form from my details" title="Fill this form from my details" onClick={onFill}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
            <TextCursorInput className="h-3.5 w-3.5" />
          </button>
        )}
        {toggle}
      </div>
    )

  return (
    <div className="mx-3 mt-3 shrink-0 rounded-xl border bg-card px-3 py-2.5" title={tab?.url}>
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
          {blocked ? <ShieldOff className="h-4 w-4 text-muted-foreground" />
            : tab?.favIconUrl ? <img src={tab.favIconUrl} alt="" className="h-4 w-4" />
            : app || pdf ? <FileText className="h-4 w-4 text-muted-foreground" /> : <Globe className="h-4 w-4 text-muted-foreground" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{tab?.title || "No page"}</span>
          <span className="block truncate text-xs text-muted-foreground">{blocked ? `Never read: ${blocked}` : where}</span>
        </span>
        {toggle}
      </div>
      {readable && reading && (pdf || fillable) && (
        <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
          {pdf ? (
            <button type="button" onClick={onViewer} className={TOOL}>Open in Atlas viewer</button>
          ) : (
            fillable && (
              <button type="button" onClick={onFill} className={TOOL}><TextCursorInput className="h-3.5 w-3.5" />Fill this form</button>
            )
          )}
        </div>
      )}
    </div>
  )
}

const TOOL = "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
