/**
 * Google's apps draw their documents on a canvas, so the page holds no text
 * to read. Each has an export that does: fetched here, from the page itself,
 * with the user's own session (same origin, so their login applies), and sent
 * only to their local Atlas.
 *
 * - Docs: `export?format=txt`; if that fails, the plain `mobilebasic` view.
 * - Sheets: the open tab (`gid`) as CSV through `gviz`, else `export?format=csv`.
 * - Slides: `export/txt`.
 * - Drive file pages: not read here; the panel downloads the file (a PDF) into
 *   the chat, where the pdf reader takes it (`kind: "drive-file"`).
 */

import TurndownService from "turndown"

export type GoogleApp = "document" | "spreadsheets" | "presentation" | "drive-file"

export interface GoogleTarget {
  app: GoogleApp
  id: string
  /** A sheet's open tab. */
  gid?: string
}

/** Which Google app and file a URL is, or null. */
export function googleTarget(href: string): GoogleTarget | null {
  let url: URL
  try {
    url = new URL(href)
  } catch {
    return null
  }
  if (url.hostname === "docs.google.com") {
    const m = /^\/(document|spreadsheets|presentation)\/d\/([\w-]{10,})/.exec(url.pathname)
    if (!m) return null
    const gid = /gid=(\d+)/.exec(url.hash)?.[1] ?? url.searchParams.get("gid") ?? undefined
    return { app: m[1] as GoogleApp, id: m[2], ...(m[1] === "spreadsheets" && gid ? { gid } : {}) }
  }
  if (url.hostname === "drive.google.com") {
    const m = /^\/file\/d\/([\w-]{10,})/.exec(url.pathname) ?? (url.pathname === "/open" ? [null, url.searchParams.get("id")] : null)
    return m?.[1] ? { app: "drive-file", id: m[1] } : null
  }
  return null
}

/** The address that gives a Google file's text. */
export function exportUrl(t: GoogleTarget, fallback = false): string {
  const base = `https://docs.google.com/${t.app}/d/${t.id}`
  if (t.app === "document") return fallback ? `${base}/mobilebasic` : `${base}/export?format=txt`
  if (t.app === "spreadsheets")
    return fallback ? `${base}/export?format=csv${t.gid ? `&gid=${t.gid}` : ""}`
      : `${base}/gviz/tq?tqx=out:csv${t.gid ? `&gid=${t.gid}` : ""}`
  if (t.app === "presentation") return `${base}/export/txt`
  return `https://drive.usercontent.google.com/download?id=${t.id}&export=download&confirm=t`
}

/** A Google app's title without " - Google Docs" and the like. */
export const cleanTitle = (title: string) => title.replace(/\s+-\s+Google (Docs|Sheets|Slides|Drive)$/i, "").trim()

const turndown = new TurndownService({ headingStyle: "atx", bulletListMarker: "-" })
turndown.remove(["script", "style", "noscript"])

async function text(url: string): Promise<string | null> {
  try {
    const response = await fetch(url, { credentials: "include" })
    if (!response.ok) return null
    const type = response.headers.get("content-type") ?? ""
    const body = await response.text()
    // A login or error page comes back as HTML instead of the file.
    if (type.includes("text/html")) {
      if (!url.endsWith("/mobilebasic")) return null
      const doc = new DOMParser().parseFromString(body, "text/html")
      const main = doc.querySelector(".doc-content, #contents, body")
      return main ? turndown.turndown(main.innerHTML).trim() : null
    }
    return body.trim()
  } catch {
    return null
  }
}

/** The text of the Google file this page shows, or null when it is not one (or cannot be read). */
export async function googleText(t: GoogleTarget): Promise<string | null> {
  if (t.app === "drive-file") return null
  const first = await text(exportUrl(t))
  if (first) return first
  return text(exportUrl(t, true))
}
