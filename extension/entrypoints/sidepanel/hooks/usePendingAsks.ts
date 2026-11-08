/** Questions left by the selection chip and the context menu, picked up when the panel opens. */

import { useEffect, useRef } from "react"
import { atlas, useAtlas } from "@/state/store"
import { type PendingAsk } from "@ext/shared/settings"
import { toTabInfo, type TabInfo } from "@ext/shared/tab"
import { fetchImage } from "@ext/shared/capture"
import { bindPage } from "../actions/bindPage"

// ------------------------------------------------------------- pending asks --

const PROMPTS: Record<PendingAsk["action"], (text: string, language?: string) => string> = {
  explain: (t) => `Explain this passage from the page in simple terms:\n\n“${t}”`,
  simplify: (t) => `Rewrite this passage from the page in simpler words, keeping its meaning:\n\n“${t}”`,
  define: (t) => `Define the key terms in this passage, as they are used on this page:\n\n“${t}”`,
  translate: (t, l) => `Translate this passage into ${l ?? "English"}. Reply with the translation only:\n\n“${t}”`,
  ask: (t) => `What does this passage from the page mean?\n\n“${t}”`,
  image: () => "What does this image from the page show? If it has text, read it out exactly.",
}

/** Questions left by the selection chip or the right-click menu: a new chat on that tab. */
export function usePendingAsks(ready: boolean, attach: (tab: TabInfo) => void) {
  const busy = useAtlas((s) => s.run !== null)
  const handled = useRef(0)
  useEffect(() => {
    if (!ready) return
    const take = async () => {
      const { pendingAsk } = (await browser.storage.session.get("pendingAsk")) as { pendingAsk?: PendingAsk }
      if (!pendingAsk || pendingAsk.at <= handled.current || atlas.busy) return
      handled.current = pendingAsk.at
      await browser.storage.session.remove("pendingAsk")
      const tab = await browser.tabs.get(pendingAsk.tabId)
      const info = toTabInfo(tab)
      if (!info) return
      atlas.newChat()
      attach(info)
      bindPage(info, true)
      // A selected passage: only the part of the page around it goes with the question (quick to read).
      if (pendingAsk.action !== "image") atlas.pageFocus = pendingAsk.text
      if (pendingAsk.action === "image" && pendingAsk.src) {
        const image = await fetchImage(pendingAsk.src)
        if ("error" in image) return void atlas.fail(new Error(image.error))
        const ext = image.format === "jpeg" ? "jpg" : image.format
        await atlas.attach_files([new File([image.blob], `image.${ext}`, { type: image.blob.type })])
      }
      await atlas.send(PROMPTS[pendingAsk.action](pendingAsk.text.slice(0, 4000), pendingAsk.language))
    }
    void take()
    const onChange = (changes: Record<string, unknown>, area: string) => {
      if (area === "session" && "pendingAsk" in changes) void take()
    }
    browser.storage.onChanged.addListener(onChange)
    return () => browser.storage.onChanged.removeListener(onChange)
  }, [ready, attach, busy])
}
