/**
 * The Atlas PDF viewer: a PDF in an extension page, so Atlas can read it,
 * find in it and highlight it side by side with the panel. The browser's own
 * viewer runs no content script, so none of that works there.
 *
 * pdf.js renders each page with a text layer; the page layer (`lib/page.ts`)
 * finds and highlights in that text exactly as on a web page. Reading uses
 * pdf.js's own text, page by page. The selection chip works here too.
 *
 * `?file=` is the PDF's address. A web PDF is fetched with the user's session;
 * a `file://` one (or a web one that fails) is served by the Atlas backend,
 * which reads local PDFs without the "allow access to file URLs" switch.
 */

import * as pdfjs from "pdfjs-dist"
import worker from "pdfjs-dist/build/pdf.worker.min.mjs?url"
import "pdfjs-dist/web/pdf_viewer.css"

import { selectionChip } from "@ext/chip"
import * as page from "@ext/page"
import { loadSettings } from "@ext/settings"

pdfjs.GlobalWorkerOptions.workerSrc = worker

const file = new URLSearchParams(location.search).get("file") ?? ""
const name = decodeURIComponent(file.split(/[\\/]/).pop()?.split("?")[0] ?? "") || "document.pdf"
const pageTexts: string[] = []
let myTab = -1

async function load(): Promise<ArrayBuffer> {
  const isPdf = (b: ArrayBuffer) => new TextDecoder().decode(b.slice(0, 4)) === "%PDF"
  if (/^https?:/i.test(file)) {
    try {
      const response = await fetch(file, { credentials: "include" })
      const bytes = await response.arrayBuffer()
      if (response.ok && isPdf(bytes)) return bytes
    } catch {
      /* the backend tries next */
    }
  }
  const settings = await loadSettings()
  const response = await fetch(`${settings.base.replace(/\/$/, "")}/api/extension/pdf?url=${encodeURIComponent(file)}`, {
    headers: { Authorization: `Bearer ${settings.token}` },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body?.detail ?? `Atlas could not open it (${response.status}). Is Atlas running and paired?`)
  }
  return response.arrayBuffer()
}

async function render() {
  document.title = `${name} · Atlas`
  document.getElementById("name")!.textContent = name
  ;(document.getElementById("original") as HTMLAnchorElement).href = file
  const doc = await pdfjs.getDocument({ data: await load() }).promise
  document.getElementById("info")!.textContent = `${doc.numPages} page${doc.numPages === 1 ? "" : "s"}`
  document.getElementById("status")!.remove()
  const host = document.getElementById("pages")!
  const width = Math.min(1000, innerWidth - 32)
  for (let n = 1; n <= doc.numPages; n++) {
    const pdfPage = await doc.getPage(n)
    const viewport = pdfPage.getViewport({ scale: width / pdfPage.getViewport({ scale: 1 }).width })
    const wrap = document.createElement("div")
    wrap.className = "page"
    wrap.style.width = `${viewport.width}px`
    wrap.style.height = `${viewport.height}px`
    wrap.style.setProperty("--scale-factor", String(viewport.scale))
    const canvas = document.createElement("canvas")
    const ratio = devicePixelRatio || 1
    canvas.width = viewport.width * ratio
    canvas.height = viewport.height * ratio
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    const text = document.createElement("div")
    text.className = "textLayer"
    wrap.append(canvas, text)
    host.append(wrap)
    await pdfPage.render({ canvasContext: canvas.getContext("2d")!, viewport,
                           transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined }).promise
    await new pdfjs.TextLayer({ textContentSource: pdfPage.streamTextContent(), container: text, viewport }).render()
    const content = await pdfPage.getTextContent()
    pageTexts.push(content.items.map((i) => ("str" in i ? i.str + (i.hasEOL ? "\n" : " ") : "")).join("").trim())
  }
}

/** Page operations from the side panel, addressed to this tab (extension pages get no tab messages). */
function listen() {
  browser.runtime.onMessage.addListener((message: { type?: string; target?: number; op?: string; args?: Record<string, unknown> },
                                         _sender, reply) => {
    if (message?.type !== "atlas:op" || message.target !== myTab) return
    const args = message.args ?? {}
    switch (message.op) {
      case "ping":
        return reply({ ok: true })
      case "read": {
        const content = pageTexts.map((t, i) => `--- page ${i + 1} of ${pageTexts.length} ---\n${t || "(no text: a scanned page; use page_screenshot)"}`).join("\n\n")
        return reply({ title: name, url: file, content })
      }
      case "find":
        return reply(page.find(String(args.text ?? "")))
      case "highlight":
        return reply(page.highlight((args.quotes as string[]) ?? []))
      case "scrollToQuote":
        return reply({ ok: page.scrollToQuote(Number(args.index ?? 0)) })
      case "clear":
        page.clearHighlights()
        return reply({ ok: true })
      default:
        return reply({ error: "this is a PDF: Atlas can read, find, highlight and look at it, but it has no forms, tables or images to list" })
    }
  })
}

void (async () => {
  myTab = (await browser.tabs.getCurrent())?.id ?? -1
  listen()
  const settings = await loadSettings()
  selectionChip(() => settings, () => false)
  try {
    await render()
  } catch (error) {
    const status = document.getElementById("status")
    if (status) status.textContent = error instanceof Error ? error.message : String(error)
  }
})()
