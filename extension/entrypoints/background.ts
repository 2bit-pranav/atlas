/**
 * The background worker: opens the side panel, and carries requests the
 * content script cannot make itself.
 *
 * - The toolbar icon opens the panel.
 * - "Ask Atlas" on the right-click menu, and the selection chip, leave the
 *   question in `storage.session` and open the panel, which picks it up.
 * - "Save table" rows are POSTed to the backend here: the worker holds the
 *   pairing token, which the page's own context never sees.
 * - Pairing: Atlas's own page (on 127.0.0.1 or localhost) asks whether the
 *   extension is connected, and "Connect" hands over the token, which is
 *   checked against that Atlas before it is kept.
 */

import { loadSettings, localHttp, saveSettings, type PendingAsk } from "@ext/settings"

export default defineBackground(() => {
  void browser.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })

  browser.runtime.onInstalled.addListener(async () => {
    await browser.contextMenus.removeAll() // menus outlive updates: drop any an older version made
    browser.contextMenus.create({ id: "ask-atlas", title: "Ask Atlas about “%s”", contexts: ["selection"] })
    browser.contextMenus.create({ id: "ask-atlas-image", title: "Ask Atlas about this image", contexts: ["image"] })
    void injectIntoAtlasTabs()
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
    if ((message?.type === "atlas:status" || message?.type === "atlas:pair") && localHttp(sender.url) && localHttp(message.base)) {
      void (message.type === "atlas:pair" ? pair(message.base, String(message.token ?? "")) : status(message.base)).then(reply)
      return true
    }
  })
})

/**
 * The browser does not put content scripts into tabs that were already open
 * when the extension was installed, reloaded or updated. An open Atlas page
 * would then say "not installed" until reloaded, so it gets one now.
 */
async function injectIntoAtlasTabs() {
  const tabs = await browser.tabs.query({ url: ["http://127.0.0.1/*", "http://localhost/*"] })
  for (const tab of tabs)
    if (tab.id !== undefined)
      void browser.scripting.executeScript({ target: { tabId: tab.id }, files: ["/content-scripts/content.js"] }).catch(() => undefined)
}

const trim = (base: string) => base.replace(/\/$/, "")

/** Whether `token` opens the Atlas at `base`: the backend answers 401 to a wrong one. */
async function works(base: string, token: string): Promise<boolean | null> {
  try {
    const response = await fetch(`${trim(base)}/api/health`, { headers: { Authorization: `Bearer ${token}` } })
    return response.ok
  } catch {
    return null
  }
}

/** Connected means paired with the Atlas at `base`, with a token it still accepts. */
async function status(base: string) {
  const settings = await loadSettings()
  const connected = Boolean(settings.token) && trim(settings.base) === trim(base) && (await works(base, settings.token)) === true
  return { connected, version: browser.runtime.getManifest().version }
}

async function pair(base: string, token: string) {
  const ok = token ? await works(base, token) : false
  if (ok === null) return { connected: false, error: `Atlas is not answering at ${base}` }
  if (!ok) return { connected: false, error: "Atlas did not accept the token" }
  await saveSettings({ base: trim(base), token })
  return { connected: true, version: browser.runtime.getManifest().version }
}

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
