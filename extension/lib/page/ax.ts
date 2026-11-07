/**
 * The page as its accessibility tree, condensed for a small model.
 *
 * Roles and names come from `dom-accessibility-api` (the W3C role and
 * accessible-name rules Testing Library uses), so an element is named as a
 * screen reader would name it: by its label, `aria-labelledby`, `alt`, text.
 * What comes out is Markdown-like text in page order:
 *
 *   ## Admissions 2026
 *   Applications close on 30 June. [Apply online](e4) [PDF brochure](e5)
 *   - Eligibility: 60% in HSC
 *   [textbox: Email (empty)](e7) [button: Send](e8)
 *   [navigation "Main"] [Home](e1) · [About](e2)
 *   | Date | Course |
 *
 * Every interactive element carries a ref (`e12`) that stays the same for the
 * element across snapshots, so the model can point at it ("the button e8")
 * and the panel can show it on the page (`byRef`).
 *
 * Never read: hidden content (`hidden`, `aria-hidden`, not rendered), the
 * page's scripts and styles, Atlas's own overlay, and what the user typed into
 * a field (only "filled", via `typedState`). Open shadow roots and same-origin
 * frames are walked; closed shadow roots and other sites' frames cannot be.
 */

import { computeAccessibleName, getRole } from "dom-accessibility-api"
import { tableRows } from "@ext/page/tables"
import { typedState } from "@ext/page/read"

// -------------------------------------------------------------------- refs --

const ids = new WeakMap<Element, string>()
const elements = new Map<string, WeakRef<Element>>()
let counter = 0

/** The element's ref, the same one every time it is seen. */
export function refOf(el: Element): string {
  let id = ids.get(el)
  if (!id) {
    id = `e${++counter}`
    ids.set(el, id)
    elements.set(id, new WeakRef(el))
  }
  return id
}

/** The element a ref names, if it is still on the page. */
export function byRef(id: string): Element | null {
  const el = elements.get(id.trim().replace(/^\[|\]$/g, ""))?.deref() ?? null
  return el?.isConnected ? el : null
}

// ------------------------------------------------------------------- roles --

const LANDMARKS = new Set(["main", "navigation", "banner", "contentinfo", "complementary", "search", "form",
                           "region", "dialog", "alertdialog"])
/** Landmarks around the content, not the content: shown as one line of their controls. */
const CHROME = new Set(["navigation", "banner", "contentinfo"])
const INTERACTIVE = new Set(["link", "button", "textbox", "searchbox", "checkbox", "radio", "combobox", "listbox",
                             "switch", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "slider",
                             "spinbutton", "option", "treeitem"])
const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK", "OBJECT", "EMBED", "CANVAS"])
const BLOCK_TAGS = new Set(["ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "DD", "DETAILS", "DIALOG", "DIV", "DL", "DT",
                            "FIELDSET", "FIGCAPTION", "FIGURE", "FOOTER", "FORM", "H1", "H2", "H3", "H4", "H5", "H6",
                            "HEADER", "HR", "LI", "MAIN", "NAV", "OL", "P", "PRE", "SECTION", "SUMMARY", "TABLE",
                            "TR", "UL", "BR", "CAPTION", "LEGEND", "OPTION"])

const TABLE_ROWS = 200
const MAX_NODES = 60_000

const clean = (s: string, max = 100) => {
  const t = s.replace(/\s+/g, " ").trim()
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
}

function hidden(el: Element): boolean {
  if (el.id === "atlas-ui-root") return true
  if (el.hasAttribute("hidden") || el.getAttribute("aria-hidden") === "true") return true
  // Not rendered: display:none, visibility:hidden, content-visibility. (jsdom has no layout: shown.)
  const check = (el as Element & { checkVisibility?: (o: object) => boolean }).checkVisibility
  return typeof check === "function" ? !check.call(el, { visibilityProperty: true }) : false
}

function nameOf(el: Element): string {
  try {
    return clean(computeAccessibleName(el))
  } catch {
    return clean(el.textContent ?? "")
  }
}

/** What a field holds, never what the user typed (`typedState`). */
function stateOf(el: Element, role: string): string {
  // Tag names, not instanceof: a same-origin frame's elements come from another realm.
  if (el.tagName === "SELECT") return ` = "${clean((el as HTMLSelectElement).selectedOptions[0]?.text ?? "", 40)}"`
  if (el.tagName === "INPUT") {
    const input = el as HTMLInputElement
    if (input.type === "checkbox" || input.type === "radio") return input.checked ? " (checked)" : ""
    return typedState(input)
  }
  if (el.tagName === "TEXTAREA") return typedState(el as HTMLTextAreaElement)
  if (el.getAttribute("contenteditable") === "true") return " (editable)"
  const checked = el.getAttribute("aria-checked") ?? el.getAttribute("aria-selected") ?? el.getAttribute("aria-pressed")
  if (checked === "true" && role !== "link") return " (checked)"
  if (el.getAttribute("aria-disabled") === "true" || (el as HTMLButtonElement).disabled) return " (disabled)"
  return ""
}

function token(el: Element, role: string): string {
  const name = nameOf(el) || clean(el.getAttribute("placeholder") ?? el.getAttribute("title") ?? "", 60)
  const ref = refOf(el)
  return role === "link" ? `[${name || "link"}](${ref})` : `[${role}${name ? `: ${name}` : ""}${stateOf(el, role)}](${ref})`
}

// ----------------------------------------------------------------- walking --

function children(node: Node): Node[] {
  const tag = (node as Element).tagName
  if (tag === "SLOT") {
    const assigned = (node as HTMLSlotElement).assignedNodes({ flatten: true })
    return assigned.length ? assigned : Array.from(node.childNodes)
  }
  if (tag === "IFRAME" || tag === "FRAME") {
    try {
      const body = (node as HTMLIFrameElement).contentDocument?.body   // same origin only; another site's frame throws or is null
      return body ? [body] : []
    } catch {
      return []
    }
  }
  const shadow = (node as Element).shadowRoot
  return Array.from((shadow ?? node).childNodes)
}

class Writer {
  lines: string[] = []
  size = 0
  private buf = ""
  private prefix = ""
  constructor(readonly max: number) {}
  get full() { return this.size >= this.max }
  text(s: string) { this.buf += s }
  /** End the current line; a list item's line starts with "- ". */
  flush() {
    const t = this.buf.replace(/\s+/g, " ").trim()
    if (t) this.line(this.prefix + t)
    this.buf = ""
    this.prefix = ""
  }
  item() { this.flush(); this.prefix = "- " }
  line(s: string) {
    if (this.full) return
    this.lines.push(s)
    this.size += s.length + 1
  }
}

export interface OutlineOptions {
  /** Stop after about this many characters. */
  max?: number
  /** Only what can be pointed at (links, buttons, fields), each on its own line. */
  interactiveOnly?: boolean
  /** Stop after about this long (default 1.5 s). */
  ms?: number
}

/** The accessibility tree under `root`, as condensed text. */
export function outline(root: Element, options: OutlineOptions = {}): string {
  const out = new Writer(options.max ?? 200_000)
  const only = options.interactiveOnly ?? false
  // Never hang the user's tab: a pathological page (huge, or a cycle through slots or frames)
  // gets what was read in time. Each node is visited once.
  const seen = new WeakSet<Node>()
  const deadline = performance.now() + (options.ms ?? 1500)
  let visits = 0
  let cut = false

  const walk = (node: Node | null) => {
    if (!node || out.full || cut || seen.has(node)) return
    seen.add(node)
    if (++visits > MAX_NODES || (visits % 500 === 0 && performance.now() > deadline)) {
      cut = true
      return
    }
    if (node.nodeType === Node.TEXT_NODE) {
      if (!only) out.text(` ${node.nodeValue ?? ""} `)
      return
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return
    const el = node as Element
    if (SKIP_TAGS.has(el.tagName) || hidden(el)) return
    // A password field has no ARIA role at all; it is still a field (shown only as filled or empty).
    const role = getRole(el) ?? (el.tagName === "INPUT" && (el as HTMLInputElement).type !== "hidden" ? "textbox" : "")

    if (INTERACTIVE.has(role)) {
      if (only) out.line(token(el, role))
      else out.text(` ${token(el, role)} `)
      return   // its name already says what is inside
    }
    if (role === "img" || el.tagName === "IMG") {
      const alt = nameOf(el)
      if (alt && !only) out.text(` [image: ${alt}] `)
      return
    }
    if (role === "heading") {
      if (only) return
      out.flush()
      const level = Number(el.getAttribute("aria-level") ?? /^H(\d)$/.exec(el.tagName)?.[1] ?? 2)
      const text = nameOf(el)
      if (text) out.line(`${"#".repeat(Math.min(Math.max(level, 1), 6))} ${text}`)
      return
    }
    if ((role === "table" || role === "grid") && !only) {
      const rows = tableRows(el)
      if (rows.length >= 2 && (rows[0]?.length ?? 0) >= 2) {
        out.flush()
        const caption = clean(el.querySelector("caption")?.textContent ?? nameOf(el), 80)
        if (caption) out.line(`Table: ${caption}`)
        // A table is often the page's content (a list, a timetable): all of it, within the budget.
        for (const row of rows.slice(0, TABLE_ROWS)) out.line(`| ${row.map((c) => clean(c, 60)).join(" | ")} |`)
        if (rows.length > TABLE_ROWS) out.line(`(table continues: ${rows.length - TABLE_ROWS} more rows)`)
        return
      }
    }
    if (LANDMARKS.has(role)) {
      // A header's menu keeps the menu's own name ("Main").
      const inner = CHROME.has(role) ? el.querySelector("nav[aria-label], [role=navigation][aria-label]") : null
      const name = nameOf(el) || (inner ? nameOf(inner) : "")
      out.flush()
      if (CHROME.has(role) && !only) {
        // Menus and footers: their controls on one line, not their whole text.
        const items = Array.from(el.querySelectorAll("a[href], button, [role=link], [role=button], [role=tab], [role=menuitem]"))
          .filter((x) => !hidden(x)).slice(0, 15).map((x) => token(x, getRole(x) ?? "link"))
        if (items.length) out.line(`[${role}${name ? ` "${name}"` : ""}] ${items.join(" · ")}`)
        return
      }
      if (!only && role !== "main" && role !== "form") out.line(`[${role}${name ? ` "${name}"` : ""}]`)
      else if (!only && role === "form" && name) out.line(`[form "${name}"]`)
      children(el).forEach(walk)
      out.flush()
      return
    }
    // A field's label names the field already: only the field is written, not the label's text again.
    const control = el.tagName === "LABEL" ? (el as HTMLLabelElement).control : null
    if (control) {
      // A field inside its label is written here; a label beside its field adds nothing (the field
      // is written where it is). Links in the label ("I agree to the terms") are kept.
      if (el.contains(control)) walk(control)
      el.querySelectorAll("a[href]").forEach(walk)
      return
    }
    const block = BLOCK_TAGS.has(el.tagName) || role === "listitem" || role === "row" || role === "paragraph"
    if (block) {
      if (el.tagName === "LI" || role === "listitem") out.item()
      else out.flush()
    }
    children(el).forEach(walk)
    if (block) out.flush()
  }

  walk(root)
  out.flush()
  if (out.full || cut) out.lines.push("(the page continues)")
  return out.lines.join("\n")
}

/** A ref's element, scrolled into view and outlined for a moment: "show me the Apply button". */
export function show(id: string): { ok: boolean; name?: string; error?: string } {
  const el = byRef(id)
  if (!el) return { ok: false, error: `there is no element ${id} on the page now; it may have changed` }
  el.scrollIntoView({ behavior: "smooth", block: "center" })
  const html = el as HTMLElement
  const before = html.style.outline
  html.style.outline = "3px solid #f59e0b"
  setTimeout(() => (html.style.outline = before), 2500)
  return { ok: true, name: nameOf(el) }
}
