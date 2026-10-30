/** Comparing pages by address, and a page's host for display. */


// ------------------------------------------------------------------ history --

/** The same page, ignoring the #fragment. */
export function sameUrl(a: string, b: string): boolean {
  return a.split("#")[0] === b.split("#")[0]
}

export function host(url: string | undefined): string {
  try {
    return url ? new URL(url).hostname.replace(/^www\./, "") : ""
  } catch {
    return ""
  }
}
