/**
 * One workspace file, rendered by type. Every renderer produces real,
 * selectable text, because selecting a passage is how the user points the
 * agent at it:
 *
 *   docx   docx-preview (in the browser, from the file's bytes)
 *   pdf    pdf.js, canvas plus its text layer
 *   xlsx   the backend's sheet preview, as tables
 *   image  <img>
 *   text   markdown rendered; csv as a table; anything else as plain text
 *
 * The heavy libraries load only when a file of their kind is opened.
 */

import { useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"

import * as api from "@/lib/api"
import type { SheetPreview } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Markdown } from "@/components/chat/Markdown"

const ext = (name: string) => name.split(".").pop()?.toLowerCase() ?? ""
const TEXT = new Set(["md", "txt", "csv", "json", "log", "py", "js", "ts", "tsx", "html", "css", "yml", "yaml", "xml", "ini", "toml"])
const IMAGE = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"])

export function FileView({ chatId, name }: { chatId: string; name: string }) {
  const kind = ext(name)
  if (kind === "docx") return <DocxView url={api.fileUrl(chatId, name)} />
  if (kind === "pdf") return <PdfView url={api.fileUrl(chatId, name)} />
  if (kind === "xlsx" || kind === "xlsm") return <SheetView chatId={chatId} name={name} />
  if (IMAGE.has(kind)) return <div className="p-4"><img src={api.fileUrl(chatId, name)} alt={name} className="mx-auto max-w-full" /></div>
  if (TEXT.has(kind)) return <TextView url={api.fileUrl(chatId, name)} kind={kind} />
  if (kind === "wav" || kind === "mp3" || kind === "webm" || kind === "ogg")
    return <div className="p-6"><audio controls src={api.fileUrl(chatId, name)} className="w-full" /></div>
  return <Unsupported />
}

function Loading() {
  return <div className="flex h-40 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
}

function Failed({ message }: { message: string }) {
  return <p className="p-6 text-sm text-destructive">Could not show this file: {message}</p>
}

function Unsupported() {
  return <p className="p-6 text-sm text-muted-foreground">No preview for this file type. Use Download to open it.</p>
}

function useFetched<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: string }>({})
  useEffect(() => {
    let live = true
    load().then((data) => live && setState({ data }), (e: unknown) => live && setState({ error: String(e) }))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

function DocxView({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const [{ renderAsync }, blob] = await Promise.all([
          import("docx-preview"),
          fetch(url).then((r) => { if (!r.ok) throw new Error(r.statusText); return r.blob() }),
        ])
        if (!live || !host.current) return
        host.current.innerHTML = ""
        await renderAsync(blob, host.current, undefined, {
          className: "docx", inWrapper: true, breakPages: true, ignoreLastRenderedPageBreak: true,
        })
        if (live) setReady(true)
      } catch (e) {
        if (live) setError(String(e))
      }
    })()
    return () => {
      live = false
    }
  }, [url])
  if (error) return <Failed message={error} />
  return (
    <>
      {!ready && <Loading />}
      {/* docx-preview draws white pages; keep them white in dark mode too. */}
      <div ref={host} className="docx-host [&_.docx-wrapper]:bg-muted/40 [&_.docx-wrapper]:p-4 [&_section.docx]:shadow-md" />
    </>
  )
}

function PdfView({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const pdfjs = await import("pdfjs-dist")
        const worker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default
        await import("pdfjs-dist/web/pdf_viewer.css")
        pdfjs.GlobalWorkerOptions.workerSrc = worker
        const doc = await pdfjs.getDocument(url).promise
        const el = host.current
        if (!live || !el) return
        el.innerHTML = ""
        const width = el.clientWidth - 32
        for (let n = 1; n <= doc.numPages; n++) {
          const page = await doc.getPage(n)
          const base = page.getViewport({ scale: 1 })
          const viewport = page.getViewport({ scale: width / base.width })
          const wrap = document.createElement("div")
          wrap.className = "relative mx-auto mb-4 bg-white shadow-md"
          wrap.style.width = `${viewport.width}px`
          wrap.style.height = `${viewport.height}px`
          wrap.style.setProperty("--scale-factor", String(viewport.scale))
          const canvas = document.createElement("canvas")
          const ratio = window.devicePixelRatio || 1
          canvas.width = viewport.width * ratio
          canvas.height = viewport.height * ratio
          canvas.style.width = `${viewport.width}px`
          canvas.style.height = `${viewport.height}px`
          const text = document.createElement("div")
          text.className = "textLayer"
          wrap.append(canvas, text)
          el.append(wrap)
          await page.render({ canvasContext: canvas.getContext("2d")!, viewport,
                              transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined }).promise
          await new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: text, viewport }).render()
          if (!live) return
        }
        setReady(true)
      } catch (e) {
        if (live) setError(String(e))
      }
    })()
    return () => {
      live = false
    }
  }, [url])
  if (error) return <Failed message={error} />
  return (
    <>
      {!ready && <Loading />}
      <div ref={host} className="bg-muted/40 p-4" />
    </>
  )
}

function SheetView({ chatId, name }: { chatId: string; name: string }) {
  const { data, error } = useFetched<SheetPreview>(() => api.sheetPreview(chatId, name), [chatId, name])
  const [index, setIndex] = useState(0)
  if (error) return <Failed message={error} />
  if (!data) return <Loading />
  const sheet = data.sheets[Math.min(index, data.sheets.length - 1)]
  return (
    <div className="flex h-full flex-col">
      {data.sheets.length > 1 && (
        <div className="flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-2">
          {data.sheets.map((s, i) => (
            <button key={s.name} type="button" onClick={() => setIndex(i)}
                    className={cn("rounded-md px-2.5 py-1 text-xs", i === index ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/60")}>
              {s.name}
            </button>
          ))}
        </div>
      )}
      {sheet && <Table rows={sheet.rows} />}
      {sheet?.truncated && <p className="p-3 text-xs text-muted-foreground">Showing the first 500 rows.</p>}
    </div>
  )
}

function Table({ rows }: { rows: string[][] }) {
  if (!rows.length) return <p className="p-6 text-sm text-muted-foreground">This sheet is empty.</p>
  const [head, ...body] = rows
  return (
    <div className="overflow-auto p-3">
      <table className="border-collapse text-xs">
        <thead>
          <tr>{head.map((c, i) => <th key={i} className="sticky top-0 border bg-muted px-2 py-1.5 text-left font-semibold">{c}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri}>{head.map((_, ci) => <td key={ci} className="border px-2 py-1 align-top">{r[ci] ?? ""}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TextView({ url, kind }: { url: string; kind: string }) {
  const { data, error } = useFetched<string>(() => fetch(url).then((r) => r.text()), [url])
  if (error) return <Failed message={error} />
  if (data === undefined) return <Loading />
  if (kind === "md") return <div className="px-6 py-4 text-[15px]"><Markdown text={data} /></div>
  if (kind === "csv") return <Table rows={data.trim().split(/\r?\n/).map((l) => l.split(","))} />
  return <pre className="whitespace-pre-wrap break-words p-4 font-mono text-xs">{data}</pre>
}
