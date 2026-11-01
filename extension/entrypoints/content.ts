/**
 * The content script: the page layer's hands in the tab.
 *
 * - Answers the side panel's page operations (read, find, highlight, scroll).
 * - The selection chip: select text, then Explain / Simplify / Define /
 *   Translate, which opens the panel with that question.
 * - Save table: select text inside a data table and the chip offers xlsx / csv.
 *   The rows go straight to the backend; no model.
 * - Fill suggestions: the form's fields out, a preview of values back, filled
 *   only on Apply, never submitted (`lib/fill/fill.ts`).
 * - Pairing, on Atlas's own page only: relays "are you connected?" and
 *   "Connect" to the background worker, which checks and keeps the token.
 *
 * Nothing runs on sites in the never-read list.
 */

import { blocked, loadSettings, localHttp, type ExtensionSettings } from "@ext/shared/settings"
import { selectionChip } from "@ext/ui/chip"
import * as fill from "@ext/fill/fill"
import { elements, readable } from "@ext/page/read"
import { tables } from "@ext/page/tables"
import { imageSrc, images } from "@ext/page/images"
import { clearHighlights, find, highlight, scrollToQuote } from "@ext/page/highlight"

type Op = { type: "atlas:op"; op: string; args: Record<string, unknown> }

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  async main() {
    let settings: ExtensionSettings = await loadSettings()
    browser.storage.onChanged.addListener((changes) => {
      if (changes.settings) void loadSettings().then((s) => (settings = s))
    })
    // After the extension is reloaded or updated, this copy is cut off from it
    // (`runtime.id` goes away) and a fresh one is injected: this one goes quiet.
    const off = () => !browser.runtime?.id || blocked(location.href, settings.neverRead) !== null

    browser.runtime.onMessage.addListener((message: Op, _sender, reply) => {
      if (message?.type !== "atlas:op") return
      if (off()) {
        reply({ error: blocked(location.href, settings.neverRead) })
        return
      }
      try {
        reply(run(message.op, message.args ?? {}))
      } catch (error) {
        reply({ error: error instanceof Error ? error.message : String(error) })
      }
    })

    selectionChip(() => settings, off)
    pairingBridge(() => !browser.runtime?.id)
  },
})

/**
 * Atlas's Browser extension page talks to the extension with `postMessage`:
 * `atlas:hello` (is it installed and connected?) and `atlas:pair` (Connect).
 * Only on a local http page, and only from the page itself; the answers say
 * whether it is connected, never the token. `atlas:ready` on arrival tells a
 * page that asked too early (a slow load, a reloaded extension) to ask again.
 */
function pairingBridge(orphaned: () => boolean) {
  if (!localHttp(location.href)) return
  addEventListener("message", (event) => {
    if (orphaned() || event.source !== window || event.origin !== location.origin) return
    const data = event.data as { type?: string; base?: string; token?: string } | null
    if (data?.type !== "atlas:hello" && data?.type !== "atlas:pair") return
    const message = data.type === "atlas:pair" ? { type: "atlas:pair", base: data.base, token: data.token } : { type: "atlas:status", base: data.base }
    void browser.runtime.sendMessage(message)
      .catch(() => ({ connected: false, error: "the extension could not check: reload this page" }))
      .then((answer) => postMessage({ type: "atlas:here", ...(answer as object) }, location.origin))
  })
  postMessage({ type: "atlas:ready" }, location.origin)
}

function run(op: string, args: Record<string, unknown>): Record<string, unknown> {
  switch (op) {
    case "ping":
      return { ok: true }
    case "read": {
      const view = String(args.view ?? "text")
      const content = view === "elements" ? elements() : view === "tables" ? tables()
        : view === "images" ? images() : readable()
      return { title: document.title, url: location.href, content }
    }
    case "find":
      return find(String(args.text ?? ""))
    case "highlight":
      return highlight((args.quotes as string[]) ?? [])
    case "scrollToQuote":
      return { ok: scrollToQuote(Number(args.index ?? 0)) }
    case "imageSrc": {
      const src = imageSrc(Number(args.index ?? 0))
      return src ? { src } : { error: `there is no image ${Number(args.index ?? 0) + 1} on the page` }
    }
    case "formFields":
      return { fields: fill.formFields(), title: document.title }
    case "previewFill":
      return fill.previewFill((args.values as Record<string, string>) ?? {})
    case "applyFill":
      return fill.applyFill()
    case "discardFill":
      return fill.discardFill()
    case "clear":
      clearHighlights()
      return { ok: true }
    default:
      return { error: `unknown page operation ${op}` }
  }
}
