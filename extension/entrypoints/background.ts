/**
 * The background worker: opens the side panel, and carries requests the
 * content script cannot make itself.
 *
 * - The toolbar icon opens the panel.
 * - "Ask Atlas" on the right-click menu, and the selection chip, leave the
 *   question in `storage.session` and open the panel, which picks it up.
 * - "Save table" rows are POSTed to the backend here: the worker holds the
 *   pairing token, which the page's own context never sees.
 */

import { loadSettings, type PendingAsk } from "@ext/settings"

export default defineBackground(() => {
  void browser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })

  browser.runtime.onInstalled.addListener(() => {
    browser.contextMenus.create({ id: "ask-atlas", title: "Ask Atlas about “%s”", contexts: ["selection"] })
    browser.contextMenus.create({ id: "ask-atlas-image", title: "Ask Atlas about this image", contexts: ["image"] })
    browser.contextMenus.create({ id: "save-table", title: "Save this table as a spreadsheet", contexts: ["page", "selection"] })
  })

  // Opening must happen in the same task as the user's click: no await before it.
  const openAndAsk = (tabId: number, ask: Omit<PendingAsk, "tabId" | "at">) => {
    const opened = browser.sidePanel.open({ tabId }).then(() => true, () => false)
    void browser.storage.session.set({ pendingAsk: { ...ask, tabId, at: Date.now() } satisfies PendingAsk })
    return opened
  }

  browser.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "ask-atlas" && tab?.id !== undefined && info.selectionText)
      void openAndAsk(tab.id, { action: "ask", text: info.selectionText })
    if (info.menuItemId === "ask-atlas-image" && tab?.id !== undefined && info.srcUrl)
      void openAndAsk(tab.id, { action: "image", text: "", src: info.srcUrl })
    // The content script knows what was right-clicked; it finds the table there.
    if (info.menuItemId === "save-table" && tab?.id !== undefined)
      void browser.tabs.sendMessage(tab.id, { type: "atlas:saveTableHere", format: "xlsx" }).catch(() => undefined)
  })

  browser.runtime.onMessage.addListener((message, sender, reply) => {
    if (message?.type === "atlas:ask" && sender.tab?.id !== undefined) {
      void openAndAsk(sender.tab.id, { action: message.action, text: message.text, language: message.language })
        .then((opened) => reply({ opened }))
      return true
    }
    if (message?.type === "atlas:saveTable") {
      void saveTable(message).then(reply)
      return true
    }
  })
})

async function saveTable(message: { rows: string[][]; title: string; url: string; format: string }) {
  const settings = await loadSettings()
  if (!settings.token) return { error: "the extension is not paired: open the Atlas panel" }
  try {
    const response = await fetch(`${settings.base.replace(/\/$/, "")}/api/extension/table`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${settings.token}` },
      body: JSON.stringify({ rows: message.rows, title: message.title, url: message.url,
                             format: message.format, folder: settings.tablesFolder }),
    })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) return { error: body?.detail ?? `${response.status}` }
    return { path: body.path }
  } catch {
    return { error: "Atlas is not running (`atlas start`)" }
  }
}
