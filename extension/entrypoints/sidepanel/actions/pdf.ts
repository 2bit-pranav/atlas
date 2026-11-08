/** PDF tabs: recognising them, naming them, attaching one to the chat. */

import * as api from "@/api/client"

// --------------------------------------------------------------------- PDFs --

export function isPdf(url: string): boolean {
  try {
    const parsed = new URL(url)
    return /\.pdf$/i.test(decodeURIComponent(parsed.pathname)) && /^(https?|file):$/.test(parsed.protocol)
  } catch {
    return false
  }
}

export function pdfName(url: string): string {
  try {
    const name = decodeURIComponent(new URL(url).pathname.split("/").pop() ?? "")
    return name || "document.pdf"
  } catch {
    return "document.pdf"
  }
}

/**
 * The tab's PDF into the chat. A web PDF is fetched here, with the user's
 * session, so one behind a login works; if that fails, and for `file://`,
 * the backend copies it (no "allow access to file URLs" switch needed).
 */
export async function savePdf(chatId: string, url: string, name = pdfName(url)) {
  if (/^https?:/i.test(url)) {
    try {
      const response = await fetch(url, { credentials: "include" })
      const blob = await response.blob()
      const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer())
      if (response.ok && String.fromCharCode(...head) === "%PDF")
        return await api.uploadFile(chatId, new File([blob], name, { type: "application/pdf" }))
    } catch {
      /* the backend tries next */
    }
  }
  return api.importFile(chatId, url)
}
