/**
 * The document panel on the right, like Claude's: a workspace file rendered
 * in place, with any passage selectable and sendable to the agent.
 *
 * Selecting text shows "Ask about this"; it adds the passage to the composer
 * as a reference (`Ref`), and the backend tells the model which file it came
 * from and where that file is -- enough for a precise `edit_document`.
 *
 * The panel lists every file in the chat's workspace, not just the ones on
 * screen, so a document made by a turn that was later edited away is still
 * here.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import * as Dropdown from "@radix-ui/react-dropdown-menu"
import { ChevronDown, Download, FileText, MessageSquareQuote, RefreshCw, X } from "lucide-react"

import * as api from "@/lib/api"
import { atlas, useAtlas } from "@/lib/store"
import type { WorkspaceFile } from "@/lib/types"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/components/chat/Composer"
import { Tip } from "@/components/ui/tip"
import { FileView } from "@/components/preview/FileView"

const WIDTH_KEY = "atlas-preview-width"

export function PreviewPanel() {
  const chatId = useAtlas((s) => s.chat?.id ?? null)
  const name = useAtlas((s) => s.preview)
  const tick = useAtlas((s) => s.previewTick)
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [width, setWidth] = useState(() => {
    try {
      return Number(localStorage.getItem(WIDTH_KEY)) || Math.round(window.innerWidth * 0.42)
    } catch {
      return Math.round(window.innerWidth * 0.42)
    }
  })
  const body = useRef<HTMLDivElement>(null)
  const [selection, setSelection] = useState<{ text: string; x: number; y: number } | null>(null)

  useEffect(() => {
    if (!chatId || !name) return
    api.listWorkspace(chatId).then(setFiles).catch(() => setFiles([]))
  }, [chatId, name, tick])

  // Offer "Ask about this" for a selection inside the document.
  const onMouseUp = useCallback(() => {
    const sel = window.getSelection()
    const text = sel?.toString().trim() ?? ""
    if (!sel || !text || !body.current || !sel.rangeCount ||
        !body.current.contains(sel.getRangeAt(0).commonAncestorContainer)) {
      setSelection(null)
      return
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect()
    const box = body.current.getBoundingClientRect()
    setSelection({ text: text.slice(0, 2000), x: Math.min(rect.left - box.left + rect.width / 2, box.width - 80),
                   y: rect.top - box.top + body.current.scrollTop - 40 })
  }, [])

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = width
    const move = (ev: PointerEvent) => {
      const next = Math.max(320, Math.min(window.innerWidth * 0.7, startW + (startX - ev.clientX)))
      setWidth(next)
    }
    const up = () => {
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", up)
      setWidth((w) => {
        try {
          localStorage.setItem(WIDTH_KEY, String(Math.round(w)))
        } catch {
          /* not remembered */
        }
        return w
      })
    }
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", up)
  }

  if (!chatId || !name) return null
  const current = files.find((f) => f.name === name)

  return (
    <aside style={{ width }} className="relative hidden h-full shrink-0 flex-col border-l bg-background md:flex">
      <div onPointerDown={startResize} title="Drag to resize"
           className="absolute -left-1 top-0 z-10 h-full w-2 cursor-col-resize hover:bg-primary/10" />

      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <Dropdown.Root>
          <Dropdown.Trigger asChild>
            <button type="button" className="flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-sm font-medium hover:bg-accent">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{name}</span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </button>
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content align="start" sideOffset={4}
                              className="z-50 max-h-80 min-w-64 overflow-y-auto rounded-lg border bg-popover p-1 text-sm shadow-md">
              <p className="px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground/70">Workspace</p>
              {files.map((f) => (
                <Dropdown.Item key={f.name} onSelect={() => atlas.openPreview(f.name)}
                               className={cn("flex cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-accent",
                                             f.name === name && "font-medium")}>
                  <span className="truncate">{f.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(f.size)}</span>
                </Dropdown.Item>
              ))}
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
        <span className="flex-1" />
        {current && <span className="mr-1 text-xs text-muted-foreground">{formatBytes(current.size)}</span>}
        <Tip label="Reload">
          <button type="button" onClick={() => atlas.openPreview(name)} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </Tip>
        <Tip label="Download">
          <a href={api.fileUrl(chatId, name, true)} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent">
            <Download className="h-3.5 w-3.5" />
          </a>
        </Tip>
        <Tip label="Close">
          <button type="button" onClick={() => atlas.closePreview()} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent">
            <X className="h-4 w-4" />
          </button>
        </Tip>
      </header>

      <div ref={body} onMouseUp={onMouseUp} onScroll={() => setSelection(null)}
           className="relative min-h-0 flex-1 overflow-auto">
        <FileView key={`${name}:${tick}`} chatId={chatId} name={name} />
        {selection && (
          <button
            type="button"
            style={{ left: selection.x, top: Math.max(4, selection.y) }}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              atlas.addRef({ file: name, path: null, quote: selection.text })
              window.getSelection()?.removeAllRanges()
              setSelection(null)
            }}
            className="absolute z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-lg"
          >
            <MessageSquareQuote className="h-3.5 w-3.5" />Ask about this
          </button>
        )}
      </div>
    </aside>
  )
}
