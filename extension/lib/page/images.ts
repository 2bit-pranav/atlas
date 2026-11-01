/** The page's images: listing them for the model, and the address of one. */

import { visible } from "@ext/page/read"

// ----------------------------------------------------------------- images --

/** Images worth looking at: visible and at least 64 px, in page order. */
export function pageImages(): HTMLImageElement[] {
  return Array.from(document.images).filter((img) => visible(img) && img.naturalWidth >= 64 && img.naturalHeight >= 64)
}

export function images(): string {
  const found = pageImages().slice(0, 30)
  if (!found.length) return "No images on this page."
  return found.map((img, i) => {
    const caption = img.closest("figure")?.querySelector("figcaption")?.textContent?.trim()
    const what = (img.alt || img.title || caption || "").replace(/\s+/g, " ").trim().slice(0, 100)
    return `Image ${i + 1}: ${img.naturalWidth}x${img.naturalHeight}${what ? ` "${what}"` : ""}`
  }).join("\n")
}

/** The address of image `i`, for the panel to fetch (it can reach other sites; the page cannot). */
export function imageSrc(i: number): string | null {
  return pageImages()[i]?.currentSrc || pageImages()[i]?.src || null
}
