/**
 * Images for the model: the visible tab, or one image from the page.
 *
 * Done in the panel, not the content script: capturing the tab and fetching
 * an image from another site (with the user's session) are extension powers
 * a page does not have.
 */

const MAX_BYTES = 8 * 1024 * 1024

function base64(bytes: Uint8Array): string {
  let out = ""
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(out)
}

/** The visible part of the tab, as JPEG. The tab must be the one showing in its window. */
export async function screenshot(tabId: number): Promise<{ data: string; format: string } | { error: string }> {
  const tab = await browser.tabs.get(tabId)
  if (!tab.active) return { error: "switch to the page's tab first: only the visible tab can be captured" }
  try {
    const url = await browser.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 85 })
    return { data: url.slice(url.indexOf(",") + 1), format: "jpeg" }
  } catch (error) {
    return { error: `this page cannot be captured (${error instanceof Error ? error.message : String(error)})` }
  }
}

/** An image by its address, fetched with the user's session. */
export async function fetchImage(src: string): Promise<{ data: string; format: string; blob: Blob } | { error: string }> {
  try {
    const response = await fetch(src, { credentials: "include" })
    if (!response.ok) return { error: `the image did not load (${response.status})` }
    const blob = await response.blob()
    if (blob.size > MAX_BYTES) return { error: "the image is larger than 8 MB" }
    const format = (blob.type.split("/")[1] || "jpeg").replace("jpg", "jpeg").replace("svg+xml", "svg")
    if (!["jpeg", "png", "gif", "webp"].includes(format)) return { error: `cannot look at ${blob.type || "this kind of"} images` }
    return { data: base64(new Uint8Array(await blob.arrayBuffer())), format, blob }
  } catch (error) {
    return { error: `the image could not be fetched (${error instanceof Error ? error.message : String(error)})` }
  }
}

export function dataUrlToFile(dataUrl: string, name: string): File {
  const [head, body] = dataUrl.split(",")
  const type = /data:([^;]+)/.exec(head)?.[1] ?? "image/jpeg"
  const bytes = Uint8Array.from(atob(body), (c) => c.charCodeAt(0))
  return new File([bytes], name, { type })
}
