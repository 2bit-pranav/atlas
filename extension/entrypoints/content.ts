/**
 * The content script: the page layer's hands in the tab.
 *
 * - Answers the side panel's page operations: the snapshot sent with a message
 *   (`lib/page/snapshot.ts`), read, find, highlight, show an element by its ref.
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
import { outline, show } from "@ext/page/ax"
import { snapshot } from "@ext/page/snapshot"
import { basketDrops } from "@ext/page/basket"
import { toast } from "@ext/ui/overlay"
import { tables } from "@ext/page/tables"
import { imageSrc, images } from "@ext/page/images"
import { clearHighlights, find, go, highlight, point, scrollToQuote, type Pointer } from "@ext/page/highlight"

type Op = { type: "atlas:op"; op: string; args: Record<string, unknown> }

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  // In frames too, for basket drops only: Google Forms' upload dialog is a frame of another Google site.
  allFrames: true,
  async main() {
    let settings: ExtensionSettings = await loadSettings()
    browser.storage.onChanged.addListener((changes) => {
      if (changes.settings) void loadSettings().then((s) => (settings = s))
    })
    // After the extension is reloaded or updated, this copy is cut off from it
    // (`runtime.id` goes away) and a fresh one is injected: this one goes quiet.
    const off = () => !browser.runtime?.id || blocked(location.href, settings.neverRead) !== null
    basketDrops((text, failed) => toast(text, failed, 6000), off)
    // Everything else is the top page's alone: a frame never answers for the page.
    if (window !== window.top) return

    browser.runtime.onMessage.addListener((message: Op, _sender, reply) => {
      if (message?.type !== "atlas:op") return
      if (off()) {
        reply({ error: blocked(location.href, settings.neverRead) })
        return
      }
      // Async (a Google export is fetched): answered when ready, the channel kept open.
      Promise.resolve().then(() => run(message.op, message.args ?? {}))
        .then(reply, (error) => reply({ error: error instanceof Error ? error.message : String(error) }))
      return true
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

async function run(op: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  switch (op) {
    case "ping":
      return { ok: true }
    case "snapshot":
      return { ...(await snapshot(typeof args.focus === "string" ? args.focus : undefined)) }
    case "read": {
      const view = String(args.view ?? "text")
      if (view === "text") return { ...(await snapshot()) }
      const main = document.querySelector("main, [role=main]") ?? document.body
      const content = view === "elements" ? outline(main, { interactiveOnly: true, max: 12000 })
        : view === "tables" ? tables() : images()
      return { title: document.title, url: location.href, content }
    }
    case "show":
      return show(String(args.ref ?? ""))
    case "point":
      return point((args.pointers as Pointer[]) ?? [])
    case "go":
      return go(Number(args.index ?? 0))
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
