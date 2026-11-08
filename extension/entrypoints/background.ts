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

import { loadSettings, localHttp, samePlace, saveSettings, type PendingAsk } from "@ext/shared/settings"

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
    if (message?.type === "atlas:basketFile" && sender.tab?.id !== undefined) {
      // A basket card dropped on a page: the file comes from the local Atlas with the
      // pairing token, which never reaches the page. Only basket ids are accepted.
      void basketFile(String(message.id ?? "")).then(reply)
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
  const settings = await loadSettings()
  if (!samePlace(settings.base, base))
    return { connected: false, error: `The extension is set to use Atlas at ${settings.base}. ` +
                                      "To use this one, change the address in the extension's Settings." }
  const ok = token ? await works(base, token) : false
  if (ok === null) return { connected: false, error: `Atlas is not answering at ${base}` }
  if (!ok) return { connected: false, error: "Atlas did not accept the token" }
  await saveSettings({ token })
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

/** One basket file, read from Atlas now, as base64 for the content script to hand to the page. */
async function basketFile(id: string): Promise<{ name?: string; type?: string; b64?: string; error?: string }> {
  if (!/^b-[\w-]{8,40}$/.test(id)) return { error: "not a basket file" }
  const settings = await loadSettings()
  if (!settings.token) return { error: "the extension is not paired: open the Atlas panel" }
  try {
    const response = await fetch(`${settings.base.replace(/\/$/, "")}/api/extension/basket/${id}`, {
      headers: { Authorization: `Bearer ${settings.token}` },
    })
    if (!response.ok) return { error: ((await response.json().catch(() => ({}))) as { detail?: string }).detail ?? `Atlas answered ${response.status}` }
    const name = decodeURIComponent(/filename\*?=(?:UTF-8'')?"?([^";]+)/i.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? "file")
    const blob = await response.blob()
    const bytes = new Uint8Array(await blob.arrayBuffer())
    let binary = ""
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
    return { name, type: blob.type || "application/octet-stream", b64: btoa(binary) }
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) }
  }
}

