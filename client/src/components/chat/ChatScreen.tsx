/**
 * The chat, after llama.cpp's `ChatScreen`: a 48rem column, a greeting with
 * the composer centred while the chat is empty, and the composer pinned to
 * the bottom once there is something to read.
 *
 * Auto-scroll follows the answer only while the reader is already at the
 * bottom; scrolling up stops it, and the round arrow brings it back.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { ArrowDown, Upload } from "lucide-react"

import { atlas, useAtlas } from "@/lib/store"
import { TurnRow } from "@/components/chat/Messages"
import { Composer } from "@/components/chat/Composer"
import { cn } from "@/lib/utils"

export function ChatScreen() {
  const chat = useAtlas((s) => s.chat)
  const live = useAtlas((s) => s.live)
  const runTurn = useAtlas((s) => s.run?.turn_id ?? null)
  const turns = chat?.turns ?? []
  const empty = turns.length === 0

  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const [showDown, setShowDown] = useState(false)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)

  const toBottom = useCallback((smooth = false) => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" })
  }, [])

  // A different chat: start at the bottom, following.
  useLayoutEffect(() => {
    pinned.current = true
    toBottom()
  }, [chat?.id, toBottom])

  // New content: follow only if the reader has not scrolled away.
  useLayoutEffect(() => {
    if (pinned.current) toBottom()
  }, [turns.length, live, toBottom])

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onScroll = () => {
      const gap = el.scrollHeight - el.scrollTop - el.clientHeight
      pinned.current = gap < 80
      setShowDown(gap > 240)
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

  return (
    <div
      className="relative flex h-full min-h-0 flex-col"
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
        <div className={cn("mx-auto flex w-full max-w-3xl flex-col px-4",
                           empty ? "h-full justify-center pb-24" : "pb-10 pt-6")}>
          {empty ? (
            <div className="text-balance px-4 text-center">
              <h1 className="mb-2 text-2xl font-semibold tracking-tight md:text-3xl">Hello there</h1>
              <p className="text-muted-foreground md:text-lg">Type a message or upload files to get started</p>
              <div className="mt-8 text-left"><Composer /></div>
            </div>
          ) : (
            turns.map((turn, i) => (
              <TurnRow
                key={turn.id}
                turn={turn}
                chatId={chat!.id}
                isLast={i === turns.length - 1}
                laterCount={turns.length - 1 - i}
                liveParts={turn.id === runTurn ? live?.parts ?? [] : null}
                liveStats={turn.id === runTurn ? live?.stats ?? null : null}
              />
            ))
          )}
        </div>
      </div>

      {!empty && (
        <div className="relative px-4 pb-4">
          <div className="pointer-events-none absolute inset-x-0 -top-24 h-24 bg-gradient-to-t from-background to-transparent" />
          {showDown && (
            <button type="button" onClick={() => { pinned.current = true; toBottom(true) }} aria-label="Scroll to bottom"
                    className="absolute -top-14 left-1/2 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border/20 bg-muted/60 shadow-sm backdrop-blur hover:bg-muted">
              <ArrowDown className="h-4 w-4" />
            </button>
          )}
          <Composer />
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
  )
}
