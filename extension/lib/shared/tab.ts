/** Talking to the page in a tab: a content script, or the Atlas PDF viewer. */

export interface TabInfo {
  id: number
  /** The page's address; for the Atlas PDF viewer, the PDF's own address. */
  url: string
  title: string
  favIconUrl?: string
  /** The tab is the Atlas PDF viewer (an extension page, not a content script). */
  viewer?: boolean
}

const VIEWER = () => browser.runtime.getURL("/viewer.html")

/** The Atlas viewer for a PDF address. */
export function viewerUrl(file: string): string {
  return `${VIEWER()}?file=${encodeURIComponent(file)}`
}

export function toTabInfo(tab: { id?: number; url?: string; title?: string; favIconUrl?: string }): TabInfo | null {
  if (tab.id === undefined) return null
  const url = tab.url ?? ""
  if (url.startsWith(VIEWER())) {
    const file = new URL(url).searchParams.get("file") ?? ""
    return { id: tab.id, url: file, title: tab.title ?? "", favIconUrl: tab.favIconUrl, viewer: true }
  }
  return { id: tab.id, url, title: tab.title ?? "", favIconUrl: tab.favIconUrl }
}

export async function activeTab(): Promise<TabInfo | null> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true })
  return tab ? toTabInfo(tab) : null
}

const UNREADABLE = "Atlas cannot read this page: browser pages, the PDF viewer and extension stores are off limits."

/**
 * Run a page operation in the tab. A tab opened before the extension was
 * installed has no content script yet: it is injected once and the call
 * retried. The Atlas PDF viewer is an extension page and is messaged directly.
 */
export async function tabCall(tabId: number, op: string, args: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  const tab = await browser.tabs.get(tabId).catch(() => null)
  if (tab?.url?.startsWith(VIEWER()))
    return ((await browser.runtime.sendMessage({ type: "atlas:op", target: tabId, op, args })) as Record<string, unknown>)
      ?? { error: "the Atlas PDF viewer did not answer" }
  const message = { type: "atlas:op", op, args }
  try {
    return ((await browser.tabs.sendMessage(tabId, message)) as Record<string, unknown>) ?? { error: UNREADABLE }
  } catch {
    try {
      await browser.scripting.executeScript({ target: { tabId }, files: ["/content-scripts/content.js"] })
      return ((await browser.tabs.sendMessage(tabId, message)) as Record<string, unknown>) ?? { error: UNREADABLE }
    } catch {
      return { error: UNREADABLE }
    }
  }
}
