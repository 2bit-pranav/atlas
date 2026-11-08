/** The panel's start screen: what to do with this page, and earlier chats on the same site. */

import { Clock, FileSpreadsheet, FolderOpen, ListTree, Search, Sparkles, TextCursorInput } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import type { ChatSummary } from "@/api/types"
import { shortAgo, useNow } from "@/lib/time"
import { googleTarget } from "@ext/page/google"
import { isYouTubeVideo } from "@ext/page/youtube"
import { isGoogleForm } from "@ext/fill/gforms"
import { type TabInfo } from "@ext/shared/tab"

type Starter = { icon: typeof Search; label: string; send?: string; prefill?: string; fill?: boolean; wide?: boolean; hint?: string }

/** Starters by what the page is. Ones that need the user's words prefill the box; the rest send. */
function startersFor(url: string): Starter[] {
  const app = googleTarget(url)?.app
  if (isYouTubeVideo(url)) return [
    { icon: ListTree, label: "Summarise this video", send: "Summarise this video in a few points, with the time of each." },
    { icon: Clock, label: "Key moments", send: "List the key moments of this video, each with its time." },
    { icon: Search, label: "Find where they say…", prefill: "Where in the video do they talk about " },
    { icon: Sparkles, label: "Explain simply", send: "Explain what this video teaches in simple words." }]
  if (isGoogleForm(url)) return [
    { icon: TextCursorInput, label: "Fill it from my details", fill: true, wide: true,
      hint: "Shown on the form first; nothing is filled until you Apply, never submitted" },
    { icon: ListTree, label: "What does it ask for?", send: "What does this form ask for? List the questions, and which are required." },
    { icon: Sparkles, label: "Explain a question", prefill: "Explain this question on the form: " }]
  const files: Starter = { icon: FolderOpen, label: "Ask with my files", prefill: "Compare this with my ", wide: true,
                           hint: "Compare it with your resume, notes or documents" }
  if (app === "spreadsheets") return [
    { icon: ListTree, label: "Summarise this sheet", send: "Summarise what this sheet holds." },
    { icon: Search, label: "Find a value", prefill: "In this sheet, find " },
    { icon: FileSpreadsheet, label: "What stands out", send: "What stands out in these numbers? Work out any totals with calculate." },
    { icon: Sparkles, label: "Explain the columns", send: "Explain what each column of this sheet means." }, files]
  if (app === "document" || app === "presentation" || app === "drive-file") return [
    { icon: ListTree, label: "Summarise", send: "Summarise this document in a few points." },
    { icon: Search, label: "Find in it", prefill: "Where does it say " },
    { icon: Sparkles, label: "Dates and deadlines", send: "List every date and deadline in this document." },
    { icon: Sparkles, label: "Explain simply", send: "Explain this document in simple words." }, files]
  return [
    { icon: ListTree, label: "Summarise page", send: "Summarise this page in a few points." },
    { icon: Search, label: "Find on page", prefill: "Where does it say " },
    { icon: Sparkles, label: "Explain simply", send: "Explain this page in simple words." },
    { icon: FileSpreadsheet, label: "Key facts", send: "List the key facts on this page: names, dates, numbers." }, files]
}

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return ""
  }
}

export function PanelHome({ tab, reading, blocked, onOpen, onFill }: {
  tab: TabInfo | null; reading: boolean; blocked: string | null; onOpen: (c: ChatSummary) => void; onFill: () => void
}) {
  const chats = useAtlas((s) => s.chats)
  const now = useNow()
  const site = tab ? hostOf(tab.url) : ""
  const earlier = site ? chats.filter((c) => c.source === "extension" && c.page_url && hostOf(c.page_url) === site).slice(0, 3) : []

  return (
    <div className="flex flex-col gap-5 px-1 pb-4 pt-6">
      <div>
        <h1 className="font-display text-xl font-semibold tracking-tight">
          {reading && tab ? "What do you need from this page?" : "Ask Atlas"}
        </h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          {reading && tab ? "Answers point back to the page. Pages are read on this computer."
            : blocked ? `Atlas does not read this page (${blocked}). Ask anything else.`
            : "Atlas is not reading this page. Turn on Can read above to ask about it."}
        </p>
      </div>

      {reading && tab && (
        <div className="grid grid-cols-2 gap-2">
          {startersFor(tab.url).map((s) => (
            <button key={s.label} type="button"
                    onClick={() => (s.fill ? onFill() : s.send ? void atlas.send(s.send) : atlas.prefillComposer(s.prefill ?? ""))}
                    className={`flex min-h-[4.25rem] flex-col gap-1.5 rounded-xl border bg-card p-3 text-left transition-colors hover:bg-accent ${s.wide ? "col-span-2" : ""}`}>
              <s.icon className="h-4 w-4 text-run" />
              <span className="text-[13px] font-medium">{s.label}</span>
              {s.hint && <span className="text-xs text-muted-foreground">{s.hint}</span>}
            </button>
          ))}
        </div>
      )}

      {reading && tab && (
        <p className="text-xs text-muted-foreground">
          Tip: select text on the page to explain, simplify or translate it.
        </p>
      )}

      {earlier.length > 0 && (
        <section aria-label={`Earlier on ${site}`}>
          <h2 className="mb-1 text-xs font-medium text-muted-foreground">Earlier on {site}</h2>
          {earlier.map((c) => (
            <button key={c.id} type="button" onClick={() => onOpen(c)}
                    className="flex w-full justify-between gap-3 border-t px-1 py-2 text-left text-[13px] hover:bg-accent/60">
              <span className="truncate">{c.title || c.page_title || "Untitled"}</span>
              <span className="shrink-0 text-muted-foreground">{shortAgo(c.updated_at, now)}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  )
}
