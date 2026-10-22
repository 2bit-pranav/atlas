/**
 * The page layer: what Atlas can see of the page, built in code from the live
 * DOM. The model never sees HTML or class names.
 *
 * - `readable`: the content as Markdown (Readability, then Turndown); for
 *   dashboards and portals without an article, the visible text of the main
 *   region grouped by headings.
 * - `elements`: form fields, buttons and links by role and name, visible only,
 *   capped. Password values are never read.
 * - `tables`: each table's caption, header and size; `tableRows` gives the rows
 *   with merged cells expanded, for saving as a spreadsheet.
 * - `find` / `highlight`: passages located by their words and marked with the
 *   CSS Custom Highlight API, so the page's own DOM is not changed.
 */

import { Readability } from "@mozilla/readability"
import TurndownService from "turndown"

// --------------------------------------------------------------- readable --

export function visible(el: Element): boolean {
  if (el.closest("[aria-hidden='true'], [hidden], script, style, noscript, template")) return false
  const rect = (el as HTMLElement).getBoundingClientRect?.()
  if (!rect || (rect.width === 0 && rect.height === 0)) return false
  const style = getComputedStyle(el)
  return style.visibility !== "hidden" && style.display !== "none"
}

const turndown = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced", bulletListMarker: "-" })
turndown.remove(["script", "style", "noscript", "iframe", "form", "button", "input", "select", "textarea"])

export function readable(): string {
  const clone = document.cloneNode(true) as Document
  const article = new Readability(clone, { charThreshold: 400 }).parse()
  if (article?.content && (article.textContent ?? "").trim().length > 600) {
    const title = article.title ? `# ${article.title}\n\n` : ""
    return title + turndown.turndown(article.content).replace(/\n{3,}/g, "\n\n").trim()
  }
  return visibleText()
}

/** No article (a portal, a dashboard): the visible blocks of the main region, in order. */
function visibleText(): string {
  const root = document.querySelector("main, [role='main']") ?? document.body
  const out: string[] = []
  const blocks = root.querySelectorAll("h1, h2, h3, h4, p, li, td, th, dt, dd, label, blockquote, pre, figcaption, summary")
  for (const el of Array.from(blocks)) {
    if (!visible(el)) continue
    if (el.closest("td, th, li, p") !== el && el.parentElement?.closest("td, th, li, p")) continue
    const text = (el as HTMLElement).innerText?.replace(/\s+/g, " ").trim()
    if (!text) continue
    const level = /^H(\d)$/.exec(el.tagName)?.[1]
    out.push(level ? `${"#".repeat(Number(level))} ${text}` : el.tagName === "LI" ? `- ${text}` : text)
  }
  const text = out.join("\n\n").trim()
  return text || (document.body.innerText ?? "").replace(/\n{3,}/g, "\n\n").trim()
}

// --------------------------------------------------------------- elements --

const ROLES: Record<string, string> = {
  A: "link", BUTTON: "button", SELECT: "combobox", TEXTAREA: "textbox", SUMMARY: "button",
}

function role(el: Element): string {
  const explicit = el.getAttribute("role")
  if (explicit) return explicit
  if (el.tagName === "INPUT") {
    const type = (el as HTMLInputElement).type
    return { checkbox: "checkbox", radio: "radio", submit: "button", button: "button", reset: "button",
             search: "searchbox", range: "slider", file: "file" }[type] ?? "textbox"
  }
  return ROLES[el.tagName] ?? "button"
}

export function fieldName(el: Element): string {
  const aria = el.getAttribute("aria-label")
  if (aria) return aria
  const labelledBy = el.getAttribute("aria-labelledby")
  if (labelledBy) {
    const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim()
    if (text) return text
  }
  if (el.id) {
    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`)
    if (label?.textContent?.trim()) return label.textContent.trim()
  }
  const wrapping = el.closest("label")
  if (wrapping?.textContent?.trim()) return wrapping.textContent.trim()
  const placeholder = el.getAttribute("placeholder")
  if (placeholder) return placeholder
  const text = (el as HTMLElement).innerText?.trim()
  if (text) return text
  return el.getAttribute("title") ?? el.getAttribute("alt") ?? el.getAttribute("name") ?? ""
}

function state(el: Element): string {
  if (el instanceof HTMLSelectElement) {
    const options = Array.from(el.options).map((o) => o.text.trim()).filter(Boolean)
    const shown = options.length > 8 ? `${options.slice(0, 3).join(", ")} ... ${options.at(-1)}` : options.join(", ")
    return ` = "${el.selectedOptions[0]?.text.trim() ?? ""}" options: ${shown}`
  }
  if (el instanceof HTMLInputElement) {
    if (el.type === "password") return el.value ? " (filled)" : " (empty)"  // never the value
    if (el.type === "checkbox" || el.type === "radio") return el.checked ? " (checked)" : ""
    return el.value ? ` = "${el.value.slice(0, 60)}"` : " (empty)"
  }
  if (el instanceof HTMLTextAreaElement) return el.value ? ` = "${el.value.slice(0, 60)}"` : " (empty)"
  return ""
}

const INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], " +
  "[role=link], [role=tab], [role=menuitem], [role=checkbox], [role=combobox], [onclick], [tabindex]:not([tabindex='-1'])"

export function elements(limit = 40): string {
  const seen = new Set<string>()
  const groups = new Map<string, string[]>()
  let count = 0
  for (const el of Array.from(document.querySelectorAll(INTERACTIVE))) {
    if (count >= limit) break
    if (!visible(el)) continue
    const label = fieldName(el).replace(/\s+/g, " ").trim().slice(0, 80)
    if (!label) continue
    const line = `${role(el)} "${label}"${state(el)}`
    if (seen.has(line)) continue
    seen.add(line)
    const form = el.closest("form, nav, [role=dialog], [role=menu], header, footer")
    const group = form
      ? `${form.tagName === "FORM" ? "Form" : form.tagName === "NAV" ? "Navigation" : form.getAttribute("role") ?? form.tagName.toLowerCase()}` +
        (form.getAttribute("aria-label") ? ` "${form.getAttribute("aria-label")}"` : "")
      : "Page"
    groups.set(group, [...(groups.get(group) ?? []), line])
    count++
  }
  if (!count) return "No form fields, buttons or links are visible."
  const out = Array.from(groups.entries()).map(([group, lines]) => `${group}\n${lines.map((l) => `  ${l}`).join("\n")}`)
  return out.join("\n") + (count >= limit ? `\n(first ${limit} shown)` : "")
}

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

// ----------------------------------------------------------------- images --

/** Images worth looking at: visible and at least 64 px, in page order. */
export function pageImages(): HTMLImageElement[] {
  return Array.from(document.images).filter((img) => visible(img) && img.naturalWidth >= 64 && img.naturalHeight >= 64)
}

export function images(): string {
  const found = pageImages().slice(0, 30)
  if (!found.length) return "No images on this page."
  return found.map((img, i) => {
    const caption = img.closest("figure")?.querySelector("figcaption")?.textContent?.trim()
    const what = (img.alt || img.title || caption || "").replace(/\s+/g, " ").trim().slice(0, 100)
    return `Image ${i + 1}: ${img.naturalWidth}x${img.naturalHeight}${what ? ` "${what}"` : ""}`
  }).join("\n")
}

/** The address of image `i`, for the panel to fetch (it can reach other sites; the page cannot). */
export function imageSrc(i: number): string | null {
  return pageImages()[i]?.currentSrc || pageImages()[i]?.src || null
}

// -------------------------------------------------------- find, highlight --

interface Node_ {
  node: Text
  start: number
}

/** Whitespace folded and curly quotes straightened; the case is kept. */
const fold = (s: string) => s.replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/\s+/g, " ")
const norm = (s: string) => fold(s).toLowerCase()

/**
 * The page's visible text as one string, with where each text node starts in
 * it. `text` is lowercased for matching; `orig` keeps the page's case, at the
 * same positions, for showing what matched.
 */
function textIndex(): { text: string; orig: string; nodes: Node_[] } {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      const parent = n.parentElement
      if (!parent || !n.textContent?.trim()) return NodeFilter.FILTER_REJECT
      if (parent.closest("script, style, noscript, template, [aria-hidden='true'], #atlas-ui-root")) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })
  const nodes: Node_[] = []
  let orig = ""
  let block: Element | null = null
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    // A new block (paragraph, cell, heading, link...) starts with a mark that
    // no passage crosses, so a match never runs from the menu into the text.
    const here = n.parentElement?.closest(BLOCKS) ?? null
    if (here !== block && orig) orig += `${BREAK} `
    block = here
    nodes.push({ node: n as Text, start: orig.length })
    orig += fold(n.textContent ?? "") + " "
  }
  return { text: orig.toLowerCase(), orig, nodes }
}

const BREAK = "¶"
const BLOCKS = "p, li, td, th, h1, h2, h3, h4, h5, h6, dt, dd, blockquote, pre, figcaption, caption, label, " +
  "button, a, summary, nav, header, footer, section, article, div"

/** A DOM range for `[from, to)` of the index text. Approximate inside a node after whitespace folding. */
function rangeFor(index: { nodes: Node_[] }, from: number, to: number): Range | null {
  const at = (pos: number) => {
    let lo = 0
    let hi = index.nodes.length - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (index.nodes[mid].start <= pos) lo = mid
      else hi = mid - 1
    }
    const entry = index.nodes[lo]
    if (!entry) return null
    return { node: entry.node, offset: Math.min(pos - entry.start, entry.node.length) }
  }
  const a = at(from)
  const b = at(Math.max(from, to - 1))
  if (!a || !b) return null
  const range = document.createRange()
  range.setStart(a.node, Math.max(0, a.offset))
  range.setEnd(b.node, Math.min(b.node.length, b.offset + 1))
  return range
}

const STOP = new Set(["the", "and", "for", "that", "this", "with", "from", "are", "was", "where", "what", "does",
  "say", "says", "about", "page", "anything", "when", "which", "how", "is", "it", "of", "to", "in", "on", "a", "an"])

/**
 * Where `phrase` is: exact first, then the stretch holding most of its words.
 *
 * `strict` is for quotes, where "found" tells the user the page says it: only
 * words of 4+ letters count, at least two of them, and three in four must be
 * there. Loosely, "not on the page at all" came down to "not" and "all" and
 * was "found" in an unrelated paragraph.
 */
function locate(index: { text: string }, phrase: string, strict = false): [number, number] | null {
  const needle = norm(phrase).trim().replace(/^["'“”]|["'“”]$/g, "")
  if (!needle) return null
  const exact = index.text.indexOf(needle)
  if (exact >= 0) return [exact, exact + needle.length]
  // Stems, so "exams" finds "examinations" and "paid" finds "payment".
  const words = needle.split(" ").map((w) => w.replace(/[^\p{L}\p{N}]/gu, "")).filter((w) => w.length > 2 && !STOP.has(w))
    .filter((w) => !strict || w.length > 3)
    .map((w) => (w.length > 5 ? w.slice(0, w.length - 2) : w.length > 3 ? w.slice(0, 4) : w))
  if (!words.length || (strict && words.length < 2)) return null
  // The block (paragraph, cell, item) holding most of the words; a shorter
  // block wins a tie, being the more specific answer.
  let best: [number, number, number, number] | null = null  // from, to, hits, block length
  let blockStart = 0
  for (const block of index.text.split(BREAK)) {
    const hits = words.filter((w) => block.includes(w))
    if (hits.length && (!best || hits.length > best[2] || (hits.length === best[2] && block.length < best[3]))) {
      const positions = hits.map((w) => block.indexOf(w))
      const from = Math.min(...positions)
      const to = Math.max(...positions.map((p, k) => p + hits[k].length))
      best = [blockStart + from, blockStart + to, hits.length, block.length]
    }
    blockStart += block.length + BREAK.length
  }
  const needed = strict ? Math.max(2, Math.ceil(words.length * 0.75)) : Math.max(1, Math.ceil(words.length * 0.6))
  if (!best || best[2] < needed) return null
  return [best[0], best[1]]
}

/** A sentence end: ". " before a capital or a quote, not "Rs. 200" or "e.g. this". */
const SENTENCE_END = /[.!?]["')\]]?\s+(?=[A-Z"'(\[])/g

/** The sentence(s) around `[from, to)`, in the page's own case, for showing the model what matched. */
function context(orig: string, from: number, to: number): string {
  let start = Math.max(0, from - 240, orig.lastIndexOf(BREAK, from) + 1)
  const hardEnd = orig.indexOf(BREAK, to)
  let end = Math.min(orig.length, to + 240, hardEnd < 0 ? orig.length : hardEnd)
  const base = start
  for (const m of orig.slice(base, from).matchAll(SENTENCE_END)) start = Math.max(start, base + (m.index ?? 0) + m[0].length)
  const after = orig.slice(to, end)
  const stop = Array.from(after.matchAll(SENTENCE_END))[0]
  if (stop?.index !== undefined) end = to + stop.index + 1
  return orig.slice(start, end).trim()
}

let marked: Range[] = []

function paint(ranges: Range[], active = 0) {
  if (!("highlights" in CSS)) return
  ensureStyle()
  const all = new Highlight(...ranges)
  CSS.highlights.set("atlas", all)
  if (ranges[active]) CSS.highlights.set("atlas-active", new Highlight(ranges[active]))
}

function ensureStyle() {
  if (document.getElementById("atlas-highlight-style")) return
  const style = document.createElement("style")
  style.id = "atlas-highlight-style"
  style.textContent = "::highlight(atlas){background-color:rgb(253 224 71 / .5);color:inherit}" +
    "::highlight(atlas-active){background-color:rgb(250 204 21 / .9);color:#000}"
  document.head.appendChild(style)
}

export function scrollTo(i: number): boolean {
  const range = marked[i]
  if (!range) return false
  paint(marked, i)
  const el = range.startContainer.parentElement
  el?.scrollIntoView({ behavior: "smooth", block: "center" })
  return true
}

/** Find a passage by its words; highlight every match and scroll to the first. */
export function find(text: string, limit = 3): { matches: { text: string }[] } {
  const index = textIndex()
  const found: { range: Range; text: string }[] = []
  let from = 0
  // Exact repeats first, then the best fuzzy stretch.
  const needle = norm(text).trim()
  while (needle && found.length < limit) {
    const at = index.text.indexOf(needle, from)
    if (at < 0) break
    const range = rangeFor(index, at, at + needle.length)
    if (range) found.push({ range, text: context(index.orig, at, at + needle.length) })
    from = at + needle.length
  }
  if (!found.length) {
    const hit = locate(index, text)
    const range = hit && rangeFor(index, hit[0], hit[1])
    if (hit && range) found.push({ range, text: context(index.orig, hit[0], hit[1]) })
  }
  marked = found.map((f) => f.range)
  paint(marked)
  scrollTo(0)
  return { matches: found.map((f) => ({ text: f.text.slice(0, 400) })) }
}

/** Highlight each quote of an answer; which ones the page really contains. */
export function highlight(quotes: string[]): { found: boolean[] } {
  const index = textIndex()
  const ranges: (Range | null)[] = quotes.map((q) => {
    const hit = locate(index, q, true)
    return hit ? rangeFor(index, hit[0], hit[1]) : null
  })
  marked = ranges.filter((r): r is Range => r !== null)
  paint(marked)
  // `scrollTo` takes the quote's position among the found ones.
  foundOrder = ranges.map((r) => (r ? marked.indexOf(r) : -1))
  return { found: ranges.map((r) => r !== null) }
}

let foundOrder: number[] = []

export function scrollToQuote(i: number): boolean {
  const at = foundOrder[i]
  return at !== undefined && at >= 0 ? scrollTo(at) : false
}

export function clearHighlights() {
  if ("highlights" in CSS) {
    CSS.highlights.delete("atlas")
    CSS.highlights.delete("atlas-active")
  }
  marked = []
}
