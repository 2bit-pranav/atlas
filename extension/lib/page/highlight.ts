/**
 * Finding and highlighting passages: the page's text indexed once, a phrase
 * located by its words, and marked with the CSS Custom Highlight API so the
 * page's own DOM is not changed.
 */


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
