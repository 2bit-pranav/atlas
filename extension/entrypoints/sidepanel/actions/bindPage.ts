/** Pointing the shared store at one tab: what new messages are about, and how the page is read. */

import { atlas } from "@/state/store"
import { tabCall, type TabInfo } from "@ext/shared/tab"
import { pageCall } from "./pageCall"

/**
 * With `reading` on, each message carries the page as it is when sent (its
 * snapshot, `lib/page/snapshot.ts`), and the page tools and client calls run
 * in this tab. With it off (or no tab), messages are not about a page.
 */
export function bindPage(tab: TabInfo | null, reading: boolean) {
  const on = Boolean(tab && reading)
  atlas.page = on && tab ? { url: tab.url, title: tab.title } : null
  atlas.onClientCall = on && tab ? (op, args) => pageCall(tab.id, op, args) : null
  atlas.pageContent = on && tab ? async (focus) => {
    const read = await tabCall(tab.id, "snapshot", focus ? { focus } : {})
    if (read.error || typeof read.content !== "string") return null
    return { content: read.content, kind: String(read.kind ?? "page"), ...(typeof read.title === "string" && read.title ? { title: read.title } : {}) }
  } : null
}
