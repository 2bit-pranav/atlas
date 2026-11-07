/**
 * What the model gets about the page, sent with the user's message so no
 * tool call (and no extra model turn) is spent on reading it:
 *
 * - a Google Doc, Sheet or Slides deck: its text, from Google's export;
 * - a Drive file page: nothing here; the panel attaches the file itself;
 * - an article: its readable text (Readability, as Markdown), then the
 *   controls on the page with their refs;
 * - anything else (portals, apps, mail, dashboards): the accessibility tree.
 *
 * With `focus` (a passage the user selected), only the part of the page
 * around it: enough to explain or translate it, and quick.
 */

import { readable } from "@ext/page/read"
import { outline } from "@ext/page/ax"
import { cleanTitle, googleTarget, googleText, type GoogleApp } from "@ext/page/google"

export type SnapshotKind = "page" | "article" | "selection" | GoogleApp

export interface Snapshot {
  title: string
  url: string
  kind: SnapshotKind
  content: string
  /** A Drive file page: the file the panel should attach. */
  fileId?: string
}

/** The nearest block around the passage the user selected that holds a section's worth of text. */
export function around(text: string, root: Element = document.body): Element | null {
  // The start of the passage, short enough to sit in one text node.
  const needle = text.replace(/\s+/g, " ").trim().slice(0, 30).toLowerCase()
  if (!needle) return null
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let found: Element | null = null
  for (let n = walker.nextNode(); n && !found; n = walker.nextNode())
    if ((n.nodeValue ?? "").replace(/\s+/g, " ").toLowerCase().includes(needle)) found = n.parentElement
  let el = found
  while (el && el !== root && (el.textContent ?? "").trim().length < 1200
         && !/^(ARTICLE|SECTION|MAIN)$/.test(el.tagName)) el = el.parentElement
  return el ?? found
}

export async function snapshot(focus?: string): Promise<Snapshot> {
  const page = { title: document.title, url: location.href }
  const google = googleTarget(location.href)
  if (google) {
    const title = cleanTitle(document.title)
    if (google.app === "drive-file") return { title, url: page.url, kind: "drive-file", content: "", fileId: google.id }
    const text = await googleText(google)
    if (text) return { title, url: page.url, kind: google.app, content: text }
    // Not readable (no access, or an export Google refused): the tree is what is left.
  }
  if (focus) {
    const part = around(focus)
    if (part) return { ...page, kind: "selection", content: outline(part, { max: 8000 }) }
  }
  // A frameset page, or one still loading, has no <body>: its root element instead.
  const body = document.body ?? document.documentElement
  const main = document.querySelector("main, [role=main]") ?? body
  const article = readable({ articleOnly: true })
  if (article) {
    const controls = outline(main, { interactiveOnly: true, max: 2500 })
    return { ...page, kind: "article", content: controls ? `${article}\n\n## Links and controls on the page\n${controls}` : article }
  }
  return { ...page, kind: "page", content: outline(body) }
}
