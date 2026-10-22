/**
 * The selection chip and "Save this table", shared by the content script and
 * the Atlas PDF viewer.
 */

import { box, button, toast } from "./overlay"
import * as page from "./page"
import type { ExtensionSettings } from "./settings"

// ------------------------------------------------------------ selection chip --

/**
 * Shown only when the user selects text. Explain / Simplify / Define send a
 * question at once; Translate opens a row of languages (buttons, not a
 * <select>: the chip keeps the page's selection by cancelling mousedown,
 * which would also stop a native dropdown from ever opening). When the
 * selection is inside a data table, the chip also offers to save the table.
 */
export function selectionChip(settings: () => ExtensionSettings, off: () => boolean) {
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
  const label = (text: string) => {
    const el = document.createElement("span")
    el.className = "logo"
    el.textContent = text
    return el
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
      const actions = () => {
        chip!.replaceChildren(label("Atlas"),
          button("Explain", () => ask("explain", text)),
          button("Simplify", () => ask("simplify", text)),
          button("Define", () => ask("define", text)),
          button("Translate ›", languages))
        const table = anchor ? dataTable(anchor) : null
        if (table) chip!.append(label("· Table"), button("xlsx", () => void saveTable(table, "xlsx", hide)),
                                button("csv", () => void saveTable(table, "csv", hide)))
      }
      const languages = () => {
        const list = settings().languages.filter(Boolean)
        chip!.replaceChildren(button("‹", actions, "Back"), label("Translate into"),
          ...list.map((l) => button(l, () => ask("translate", text, l))))
      }
      actions()
    }, 10)
  })
  document.addEventListener("mousedown", (e) => {
    if ((e.target as Element)?.id !== "atlas-ui-root") hide()
  })
  addEventListener("scroll", hide, { passive: true })
}

// ------------------------------------------------------------- save table --

/**
 * The data table around `el`: a real <table> of at least 2 rows and 2
 * columns. ARIA grids (menus, account switchers, calendars) and one-row
 * layout tables are not offered.
 */
function dataTable(el: Element): Element | null {
  let table = el.closest("table")
  // The outermost table that is still data: layout tables nest them.
  while (table) {
    const rows = page.tableRows(table)
    if (rows.length >= 2 && (rows[0]?.length ?? 0) >= 2 && !table.closest("[role=menu], [role=dialog], nav")) return table
    table = table.parentElement?.closest("table") ?? null
  }
  return null
}

async function saveTable(table: Element, format: "xlsx" | "csv", done?: () => void) {
  done?.()
  const rows = page.tableRows(table)
  toast(`Saving ${rows.length} rows…`, false, 1500)
  const reply = await browser.runtime.sendMessage({
    type: "atlas:saveTable", rows, title: page.tableTitle(table), url: location.href, format,
  }) as { path?: string; error?: string }
  if (reply?.error) toast(`Could not save the table: ${reply.error}`, true, 7000)
  else toast(`Saved ${rows.length} rows to ${reply.path}`, false, 7000)
}

/** Right-click inside a table, "Save this table as a spreadsheet". */
export function tableMenu(off: () => boolean) {
  let target: Element | null = null
  document.addEventListener("contextmenu", (e) => {
    target = e.target as Element
  }, true)
  browser.runtime.onMessage.addListener((message: { type?: string; format?: "xlsx" | "csv" }) => {
    if (message?.type !== "atlas:saveTableHere") return
    if (off()) return void toast("Atlas does not read this site (never-read list).", true)
    const table = target ? dataTable(target) : null
    if (!table) return void toast("Right-click inside a table to save it.", true)
    void saveTable(table, message.format ?? "xlsx")
  })
}
