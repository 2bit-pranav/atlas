/**
 * The chat, after llama.cpp's `ChatScreen`: a 48rem column, a greeting with
 * the composer centred while the chat is empty, and the composer pinned to
 * the bottom once there is something to read.
 *
 * A new run brings its question to the top. Following the answer as it grows
 * is the opt-in "Auto-scroll while generating" preference; scrolling up stops
 * it, and the round arrow brings the reader back to the bottom.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { ArrowDown, ShieldAlert, Upload } from "lucide-react"

import { atlas, useAtlas } from "@/state/store"
import { usePrefs } from "@/state/prefs"
import { TurnRow } from "@/features/chat/TurnRow"
import { Composer } from "@/features/composer/Composer"
import { cn } from "@/lib/cn"
import { TaskHome } from "@/features/task/TaskHome"
import { WorkPanel, type PanelTurn } from "@/features/task/WorkPanel"
import { PanelLayout, TaskLayout } from "@/features/task/layout"

/** `layout="task"`: the web app's task view, a home page and a work panel beside the answer.
 * The extension's narrow side panel keeps the chat layout. */
export function ChatScreen({ layout = "chat", emptyView, placeholder, composerExtra, tail, composerTop }: {
  layout?: "chat" | "task" | "panel"
  /** Buttons beside the composer's + (the side panel's screenshot). */
  composerExtra?: React.ReactNode
  /** Shown under the newest answer (the side panel's follow-up pills). */
  tail?: React.ReactNode
  /** Shown just above the composer, outside the chat (the side panel's action results, like Fill's). */
  composerTop?: React.ReactNode
  /** What an empty chat shows instead of the greeting, with the composer at the bottom (the extension's start screen). */
  emptyView?: React.ReactNode
  placeholder?: string
}) {
  const task = layout === "task"
  const panel = layout === "panel"
  const chat = useAtlas((s) => s.chat)
  const live = useAtlas((s) => s.live)
  const runTurn = useAtlas((s) => s.run?.turn_id ?? null)
  const prefs = usePrefs()
  const turns = useMemo(() => chat?.turns ?? [], [chat])
  const empty = turns.length === 0
  // The panel covers every turn shown; the running one (always the newest) with its live parts.
  const panelTurns = useMemo<PanelTurn[]>(() => turns.map((t) => t.id === runTurn
    ? { turn: t, parts: live?.parts ?? [], stats: live?.stats ?? null, running: true }
    : { turn: t, parts: t.render, stats: t.stats, running: false }), [turns, runTurn, live])

  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const [showDown, setShowDown] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [viewport, setViewport] = useState(0)
  const dragDepth = useRef(0)

  const toBottom = useCallback((smooth = false) => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" })
  }, [])

  // A different chat: start at the bottom.
  useLayoutEffect(() => {
    pinned.current = true
    toBottom()
  }, [chat?.id, toBottom])

  // A new run (send, regenerate, edit): bring its question to the top and let
  // the answer grow below it, so it can be read from the first line while it
  // is still being written.
  useLayoutEffect(() => {
    const el = scroller.current
    if (!runTurn || !el) return
    const row = el.querySelector<HTMLElement>(`[data-turn-id="${runTurn}"]`)
    if (!row) return
    pinned.current = false
    el.scrollTo({ top: row.offsetTop - 16, behavior: "smooth" })
  }, [runTurn])

  // Following the stream is opt-in, and stops as soon as the reader scrolls.
  useLayoutEffect(() => {
    if (prefs.autoScroll && runTurn && pinned.current) toBottom()
  }, [live, prefs.autoScroll, runTurn, toBottom])

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onScroll = () => {
      const gap = el.scrollHeight - el.scrollTop - el.clientHeight
      pinned.current = gap < 80
      setShowDown(gap > 240)
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    const resize = new ResizeObserver(() => setViewport(el.clientHeight))
    resize.observe(el)
    return () => {
      el.removeEventListener("scroll", onScroll)
      resize.disconnect()
    }
  }, [])

  return (
    <TaskLayout.Provider value={task}>
    <PanelLayout.Provider value={panel}>
    <div className="flex h-full min-h-0 flex-col">
    {task && (
      <header className="flex min-h-13 shrink-0 items-center gap-2 border-b py-2.5 pl-14 pr-4 text-sm md:pl-4">
        {empty ? <b className="font-medium">New task</b> : (
          <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
            Tasks<span aria-hidden>/</span><b className="truncate font-medium text-foreground">{chat?.title || "New task"}</b>
          </span>
        )}
      </header>
    )}
    <div className="flex min-h-0 flex-1">
    <div
      className="relative flex h-full min-h-0 min-w-0 flex-1 flex-col"
      onDragEnter={(e) => {
        if (!e.dataTransfer.types.includes("Files")) return
        dragDepth.current += 1
        setDragging(true)
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1)
        if (!dragDepth.current) setDragging(false)
      }}
      onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        dragDepth.current = 0
        setDragging(false)
        void atlas.attach_files(Array.from(e.dataTransfer.files))
      }}
    >
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn("mx-auto flex w-full max-w-3xl flex-col", panel ? "px-3" : "px-4",
                           empty && emptyView ? "" : empty && !task ? "h-full justify-center pb-24" : empty ? "" : panel ? "pb-6 pt-2" : "pb-10 pt-6")}>
          {empty && emptyView ? emptyView : empty && task ? (
            <TaskHome />
          ) : empty ? (
            <div className="text-balance px-4 text-center">
              <h1 className="mb-2 text-2xl font-semibold tracking-tight md:text-3xl">Hello there</h1>
              <p className="text-muted-foreground md:text-lg">Type a message or upload files to get started</p>
              <div className="mt-8 text-left"><Composer /></div>
            </div>
          ) : (
            turns.map((turn, i) => (
              <div key={turn.id} style={i === turns.length - 1 ? { minHeight: Math.max(0, viewport - 40) } : undefined}>
              <TurnRow
                turn={turn}
                chatId={chat!.id}
                isLast={i === turns.length - 1}
                laterCount={turns.length - 1 - i}
                liveParts={turn.id === runTurn ? live?.parts ?? [] : null}
                liveStats={turn.id === runTurn ? live?.stats ?? null : null}
              />
              {i === turns.length - 1 && tail}
              </div>
            ))
          )}
        </div>
      </div>

      {(!empty || emptyView) && (
        <div className={cn("relative", panel ? "px-2.5 pb-2.5" : "px-4 pb-4")}>
          <div className={cn("pointer-events-none absolute inset-x-0 bg-gradient-to-t from-background to-transparent", panel ? "-top-6 h-6" : "-top-24 h-24")} />
          {showDown && (
            <button type="button" onClick={() => { pinned.current = true; toBottom(true) }} aria-label="Scroll to bottom"
                    className="absolute -top-14 left-1/2 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border/20 bg-muted/60 shadow-sm backdrop-blur hover:bg-muted">
              <ArrowDown className="h-4 w-4" />
            </button>
          )}
          {chat?.tainted && !panel ? (
            <p className="mx-auto mb-1.5 flex max-w-3xl items-center gap-1.5 px-1 text-xs text-muted-foreground"
               title="Text from outside (a web page, a fetched link, an untrusted MCP server) can carry instructions for the model. It stays in this chat's history, so this lasts for the whole chat.">
              <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
              This task has read outside content: commands, and changes outside its folder, ask you first.
            </p>
          ) : null}
          {composerTop}
          <Composer look={task ? "follow" : panel ? "panel" : "chat"} extra={composerExtra}
                    placeholder={placeholder ?? (task ? "Ask a follow-up, or tell Atlas what to change…" : undefined)} />
        </div>
      )}

      {dragging && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="rounded-2xl border-2 border-dashed border-border bg-background p-12 text-center shadow-lg">
            <Upload className="mx-auto h-12 w-12 text-muted-foreground" />
            <p className="mt-3 text-lg font-medium">Attach a file</p>
            <p className="text-sm text-muted-foreground">Drop your files here to upload</p>
          </div>
        </div>
      )}
    </div>
    {task && !empty && chat && <WorkPanel chatId={chat.id} turns={panelTurns} />}
    </div>
    </div>
    </PanelLayout.Provider>
    </TaskLayout.Provider>
  )
}
