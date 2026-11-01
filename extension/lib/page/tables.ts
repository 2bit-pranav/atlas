/** The page's tables: finding them, their rows, and a title for each. */

import { visible } from "@ext/page/read"

// ----------------------------------------------------------------- tables --

export function allTables(): Element[] {
  return Array.from(document.querySelectorAll("table, [role=grid], [role=table]"))
    .filter((t) => visible(t) && !t.parentElement?.closest("table, [role=grid], [role=table]"))
}

/** Rows of a table, with colspan/rowspan expanded into repeated cells. */
export function tableRows(table: Element): string[][] {
  const rowEls = table.tagName === "TABLE"
    ? Array.from((table as HTMLTableElement).rows)
    : Array.from(table.querySelectorAll("[role=row]"))
  const grid: string[][] = []
  const pending: Record<number, { text: string; left: number }> = {}
  rowEls.forEach((row, r) => {
    const out: string[] = []
    let col = 0
    const cells = row.tagName === "TR"
      ? Array.from((row as HTMLTableRowElement).cells)
      : Array.from(row.querySelectorAll("[role=cell], [role=gridcell], [role=columnheader], [role=rowheader]"))
    const fill = () => {
      while (pending[col]?.left) {
        out[col] = pending[col].text
        pending[col].left--
        col++
      }
    }
    for (const cell of cells) {
      fill()
      const text = ((cell as HTMLElement).innerText ?? cell.textContent ?? "").replace(/\s+/g, " ").trim()
      const span = Number(cell.getAttribute("colspan") ?? 1) || 1
      const down = Number(cell.getAttribute("rowspan") ?? 1) || 1
      for (let i = 0; i < span; i++) {
        out[col] = text
        if (down > 1) pending[col] = { text, left: down - 1 }
        col++
      }
    }
    fill()
    if (out.some((c) => c)) grid.push(out.map((c) => c ?? ""))
    void r
  })
  const width = Math.max(0, ...grid.map((r) => r.length))
  return grid.map((r) => [...r, ...Array(width - r.length).fill("")])
}

export function tableTitle(table: Element): string {
  const caption = table.querySelector("caption")?.textContent?.trim() || table.getAttribute("aria-label")
  if (caption) return caption
  let prev: Element | null = table
  for (let i = 0; i < 6 && prev; i++) {
    prev = prev.previousElementSibling ?? prev.parentElement
    const heading = prev?.matches?.("h1, h2, h3, h4") ? prev : prev?.querySelector?.("h1, h2, h3, h4")
    if (heading?.textContent?.trim()) return heading.textContent.trim()
  }
  return document.title
}

export function tables(): string {
  const found = allTables()
  if (!found.length) return "No tables on this page."
  return found.slice(0, 20).map((t, i) => {
    const rows = tableRows(t)
    const head = rows[0]?.slice(0, 8).join(" | ") ?? ""
    return `Table ${i + 1}: "${tableTitle(t).slice(0, 80)}", ${rows.length} rows x ${rows[0]?.length ?? 0} columns\n  ${head}`
  }).join("\n")
}
