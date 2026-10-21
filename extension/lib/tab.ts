/** Talking to the content script in a tab. */

export interface TabInfo {
  id: number
  url: string
  title: string
  favIconUrl?: string
}

export async function activeTab(): Promise<TabInfo | null> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id) return null
  return { id: tab.id, url: tab.url ?? "", title: tab.title ?? "", favIconUrl: tab.favIconUrl }
}

const UNREADABLE = "Atlas cannot read this page: browser pages, the PDF viewer and extension stores are off limits."

/**
 * Run a page operation in the tab. A tab opened before the extension was
 * installed has no content script yet: it is injected once and the call
 * retried.
 */
export async function tabCall(tabId: number, op: string, args: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
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
