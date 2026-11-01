/** Running a page operation in the attached tab (screenshot and image fetch in the panel itself). */

import { tabCall } from "@ext/shared/tab"
import { fetchImage, screenshot } from "@ext/shared/capture"

// ------------------------------------------------------------ page calls --

/** A page operation for the attached tab: looking is done here, the rest by the content script. */
export async function pageCall(tabId: number, op: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (op === "screenshot") return screenshot(tabId)
  if (op === "image") {
    const found = await tabCall(tabId, "imageSrc", args)
    if (found.error || typeof found.src !== "string") return found
    const image = await fetchImage(found.src)
    return "error" in image ? image : { data: image.data, format: image.format }
  }
  return tabCall(tabId, op, args)
}
