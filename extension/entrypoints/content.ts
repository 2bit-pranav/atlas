/**
 * The content script: the page layer's hands in the tab.
 *
 * - Answers the side panel's page operations (read, find, highlight, scroll).
 * - The selection chip: select text, then Explain / Simplify / Define /
 *   Translate, which opens the panel with that question.
 * - "Save table" over any table: the rows go straight to the backend as xlsx or
 *   csv. No model in the path.
 * - Fill suggestions: the form's fields out, a preview of values back, filled
 *   only on Apply, never submitted (`lib/fill.ts`).
 *
 * Nothing runs on sites in the never-read list.
 */

import { blocked, loadSettings, type ExtensionSettings } from "@ext/settings"
import { box, button, toast } from "@ext/overlay"
import * as fill from "@ext/fill"
import * as page from "@ext/page"

type Op = { type: "atlas:op"; op: string; args: Record<string, unknown> }

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  async main() {
    let settings: ExtensionSettings = await loadSettings()
    browser.storage.onChanged.addListener((changes) => {
      if (changes.settings) void loadSettings().then((s) => (settings = s))
    })
    const off = () => blocked(location.href, settings.neverRead) !== null

    browser.runtime.onMessage.addListener((message: Op, _sender, reply) => {
      if (message?.type !== "atlas:op") return
      if (off()) {
        reply({ error: blocked(location.href, settings.neverRead) })
        return
      }
      try {
        reply(run(message.op, message.args ?? {}))
      } catch (error) {
        reply({ error: error instanceof Error ? error.message : String(error) })
      }
    })

    selectionChip(() => settings, off)
    tableButtons(off)
  },
})

function run(op: string, args: Record<string, unknown>): Record<string, unknown> {
  switch (op) {
    case "ping":
      return { ok: true }
    case "read": {
      const view = String(args.view ?? "text")
      const content = view === "elements" ? page.elements() : view === "tables" ? page.tables()
        : view === "images" ? page.images() : page.readable()
      return { title: document.title, url: location.href, content }
    }
    case "find":
      return page.find(String(args.text ?? ""))
    case "highlight":
      return page.highlight((args.quotes as string[]) ?? [])
    case "scrollToQuote":
      return { ok: page.scrollToQuote(Number(args.index ?? 0)) }
    case "imageSrc": {
      const src = page.imageSrc(Number(args.index ?? 0))
      return src ? { src } : { error: `there is no image ${Number(args.index ?? 0) + 1} on the page` }
    }
    case "formFields":
      return { fields: fill.formFields(), title: document.title }
    case "previewFill":
      return fill.previewFill((args.values as Record<string, string>) ?? {})
    case "applyFill":
      return fill.applyFill()
    case "discardFill":
      return fill.discardFill()
    case "clear":
      page.clearHighlights()
      return { ok: true }
    default:
      return { error: `unknown page operation ${op}` }
  }
}

// ------------------------------------------------------------ selection chip --

function selectionChip(settings: () => ExtensionSettings, off: () => boolean) {
  let chip: HTMLDivElement | null = null
  const hide = () => {
    chip?.remove()
    chip = null
  }
  const ask = (action: string, text: string, language?: string) => {
    hide()
    void browser.runtime.sendMessage({ type: "atlas:ask", action, text, language }).then((r: { opened?: boolean }) => {
      if (!r?.opened) toast("Click the Atlas icon in the toolbar: your question is waiting in the panel.")
    })
  }

  document.addEventListener("mouseup", (event) => {
    if (off() || (event.target as Element)?.id === "atlas-ui-root") return
    setTimeout(() => {
      const selection = getSelection()
      const text = selection?.toString().trim() ?? ""
      const anchor = selection?.anchorNode?.parentElement
      if (!text || text.length > 5000 || anchor?.closest("input, textarea, [contenteditable='true']")) return hide()
      const rect = selection!.getRangeAt(0).getBoundingClientRect()
      hide()
      chip = box(rect.left, rect.bottom + 6)
      const logo = document.createElement("span")
      logo.className = "logo"
      logo.textContent = "Atlas"
      chip.append(logo,
        button("Explain", () => ask("explain", text)),
        button("Simplify", () => ask("simplify", text)),
        button("Define", () => ask("define", text)))
      const languages = settings().languages.filter(Boolean)
      const select = document.createElement("select")
      select.title = "Translate"
      select.append(new Option("Translate…", ""), ...languages.map((l) => new Option(l, l)))
      select.addEventListener("change", () => select.value && ask("translate", text, select.value))
      chip.append(select)
    }, 10)
  })
  document.addEventListener("mousedown", (e) => {
    if ((e.target as Element)?.id !== "atlas-ui-root") hide()
  })
  addEventListener("scroll", hide, { passive: true })
}

// ------------------------------------------------------------- save table --

function tableButtons(off: () => boolean) {
  let current: Element | null = null
  let bar: HTMLDivElement | null = null
  const hide = () => {
    bar?.remove()
    bar = null
    current = null
  }
  const save = async (table: Element, format: "xlsx" | "csv") => {
    const rows = page.tableRows(table)
    if (rows.length < 1) return toast("This table is empty.", true)
    toast(`Saving ${rows.length} rows…`, false, 1500)
    const reply = await browser.runtime.sendMessage({
      type: "atlas:saveTable", rows, title: page.tableTitle(table), url: location.href, format,
    }) as { path?: string; error?: string }
    if (reply?.error) toast(`Could not save the table: ${reply.error}`, true, 7000)
    else toast(`Saved ${rows.length} rows to ${reply.path}`, false, 7000)
  }
  document.addEventListener("mouseover", (event) => {
    if (off()) return
    const target = event.target as Element
    if (target?.id === "atlas-ui-root") return
    const table = target?.closest?.("table, [role=grid], [role=table]")
    if (!table || table === current) return
    if (!page.allTables().includes(table) || page.tableRows(table).length < 2) return
    hide()
    current = table
    const rect = table.getBoundingClientRect()
    bar = box(rect.right - 190, Math.max(8, rect.top - 38))
    const label = document.createElement("span")
    label.className = "logo"
    label.textContent = "Save table"
    bar.append(label, button("xlsx", () => void save(table, "xlsx")), button("csv", () => void save(table, "csv")))
  })
  addEventListener("scroll", hide, { passive: true })
}
