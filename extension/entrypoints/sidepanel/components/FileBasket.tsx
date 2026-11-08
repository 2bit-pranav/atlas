/**
 * The file basket: files Atlas found on this computer for the page's upload
 * fields (by Fill). A small bar that opens into cards; drag a card onto the
 * upload field or drop zone on the page, or download it to pick it yourself.
 *
 * A card is a reference: the file is read when it is dropped or downloaded,
 * and the card says when it moved or changed since Fill found it.
 */

import { useEffect, useState } from "react"
import { ChevronDown, Download, GripVertical, Paperclip, X } from "lucide-react"
import * as api from "@/api/client"
import { atlas } from "@/state/store"
import { cn } from "@/lib/cn"
import { formatBytes } from "@/lib/format"
import { BASKET_MIME } from "@ext/page/basket"

const TONE: Record<string, string> = {
  PDF: "bg-destructive/10 text-destructive", DOCX: "bg-run/10 text-run", DOC: "bg-run/10 text-run",
  JPG: "bg-ok/10 text-ok", JPEG: "bg-ok/10 text-ok", PNG: "bg-ok/10 text-ok",
}

export function FileBasket({ cards, onClear }: { cards: api.BasketCard[]; onClear: () => void }) {
  const [open, setOpen] = useState(false)
  const [live, setLive] = useState<api.BasketCard[]>(cards)
  useEffect(() => setLive(cards), [cards])

  // Opened: how each file is now (moved, changed, expired).
  useEffect(() => {
    if (!open || !cards.length) return
    void api.basketCards(cards.map((c) => c.id)).then((now) =>
      setLive(cards.map((c) => ({ ...c, ...(now.find((n) => n.id === c.id) ?? {}) })))).catch(() => undefined)
  }, [open, cards])

  if (!cards.length) return null

  const download = async (card: api.BasketCard) => {
    try {
      const blob = await api.basketFile(card.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = card.name ?? "file"
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (error) {
      atlas.fail(error)
    }
  }

  return (
    <section aria-label="Files Atlas found for this page" className="mx-3 mt-2 shrink-0 overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
                className="flex flex-1 items-center gap-2 px-3 py-2 text-left text-[12.5px] hover:bg-accent/50">
          <Paperclip className="h-3.5 w-3.5 text-run" />
          <span className="flex-1"><span className="font-medium">Related files</span> <span className="text-muted-foreground">· {cards.length}</span></span>
          <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
        </button>
        <button type="button" aria-label="Clear the basket" title="Clear the basket" onClick={onClear}
                className="mr-1 flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {open && (
        <div className="flex flex-col gap-1.5 border-t p-2">
          <p className="px-1 text-[11.5px] text-muted-foreground">Drag a file onto the upload field on the page, or download it.</p>
          {live.map((card) => {
            const ext = (card.name?.split(".").pop() ?? "file").slice(0, 4).toUpperCase()
            const usable = card.available !== false
            return (
              <div key={card.id} draggable={usable}
                   onDragStart={(e) => {
                     e.dataTransfer.effectAllowed = "copy"
                     e.dataTransfer.setData(BASKET_MIME, card.id)   // only the id: the page side fetches the file
                   }}
                   className={cn("flex items-center gap-2 rounded-lg border bg-background p-2",
                                 usable ? "cursor-grab active:cursor-grabbing hover:border-run/50" : "opacity-60")}>
                <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/60" />
                <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-md font-mono text-[9.5px] font-semibold", TONE[ext] ?? "bg-muted text-muted-foreground")}>{ext}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] font-medium" title={card.name}>{card.name}</span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {usable ? `${card.folder ?? ""}${card.size ? ` · ${formatBytes(card.size)}` : ""}` : card.problem}
                    {usable && card.changed && <span className="text-ask"> · changed since</span>}
                  </span>
                  {card.field && <span className="block truncate text-[11px] text-muted-foreground">for “{card.field}”</span>}
                </span>
                {usable && (
                  <button type="button" aria-label={`Download ${card.name}`} title="Download" onClick={() => void download(card)}
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border bg-card text-muted-foreground hover:bg-accent hover:text-foreground">
                    <Download className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
