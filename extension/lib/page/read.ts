/** Reading the page for the model: its readable text; a field's name and state. The element tree is ax.ts. */

import { isProbablyReaderable, Readability } from "@mozilla/readability"
import TurndownService from "turndown"

// --------------------------------------------------------------- readable --

export function visible(el: Element): boolean {
  if (el.closest("[aria-hidden='true'], [hidden], script, style, noscript, template")) return false
  const rect = (el as HTMLElement).getBoundingClientRect?.()
  if (!rect || (rect.width === 0 && rect.height === 0)) return false
  const style = getComputedStyle(el)
  return style.visibility !== "hidden" && style.display !== "none"
}

const turndown = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced", bulletListMarker: "-" })
turndown.remove(["script", "style", "noscript", "iframe", "form", "button", "input", "select", "textarea"])
// The words of a link, not its address; an image's description, not its file. Addresses cost the
// model tokens and say nothing about the page; the refs list gives what can be clicked.
turndown.addRule("linkText", { filter: "a", replacement: (content) => content })
turndown.addRule("imageAlt", {
  filter: "img",
  replacement: (_c, node) => {
    const alt = (node as HTMLImageElement).getAttribute("alt")?.trim()
    return alt ? `[image: ${alt}]` : ""
  },
})

/** The page's readable text: its article as Markdown, else (unless `articleOnly`) its visible blocks. */
export function readable(options: { articleOnly?: boolean } = {}): string {
  // Readability's own test: a link list (a news front page) or an app is not an article.
  if (options.articleOnly && !isProbablyReaderable(document)) return ""
  const clone = document.cloneNode(true) as Document
  const article = new Readability(clone, { charThreshold: 400 }).parse()
  if (article?.content && (article.textContent ?? "").trim().length > 600) {
    const title = article.title ? `# ${article.title}\n\n` : ""
    return title + turndown.turndown(article.content).replace(/\n{3,}/g, "\n\n").trim()
  }
  return options.articleOnly ? "" : visibleText()
}

/** No article (a portal, a dashboard): the visible blocks of the main region, in order. */
function visibleText(): string {
  const root = document.querySelector("main, [role='main']") ?? document.body
  const out: string[] = []
  const blocks = root.querySelectorAll("h1, h2, h3, h4, p, li, td, th, dt, dd, label, blockquote, pre, figcaption, summary")
  for (const el of Array.from(blocks)) {
    if (!visible(el)) continue
    if (el.closest("td, th, li, p") !== el && el.parentElement?.closest("td, th, li, p")) continue
    const text = (el as HTMLElement).innerText?.replace(/\s+/g, " ").trim()
    if (!text) continue
    const level = /^H(\d)$/.exec(el.tagName)?.[1]
    out.push(level ? `${"#".repeat(Number(level))} ${text}` : el.tagName === "LI" ? `- ${text}` : text)
  }
  const text = out.join("\n\n").trim()
  return text || (document.body.innerText ?? "").replace(/\n{3,}/g, "\n\n").trim()
}

// ----------------------------------------------------------------- fields --

export function fieldName(el: Element): string {
  const aria = el.getAttribute("aria-label")
  if (aria) return aria
  const labelledBy = el.getAttribute("aria-labelledby")
  if (labelledBy) {
    const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim()
    if (text) return text
  }
  if (el.id) {
    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`)
    if (label?.textContent?.trim()) return label.textContent.trim()
  }
  const wrapping = el.closest("label")
  if (wrapping?.textContent?.trim()) return wrapping.textContent.trim()
  const placeholder = el.getAttribute("placeholder")
  if (placeholder) return placeholder
  const text = (el as HTMLElement).innerText?.trim()
  if (text) return text
  return el.getAttribute("title") ?? el.getAttribute("alt") ?? el.getAttribute("name") ?? ""
}

/** Autofill kinds whose value is never shown, even one the page put there. */
const SECRET = /^(?:.*\s)?(?:one-time-code|cc-|current-password|new-password)/

/**
 * A text field's state for the model. What the user typed (an OTP, a card
 * number) is never sent; the list only says the field is filled. A value the
 * page itself put there (its default) is shown, so a prefilled form reads right.
 */
export function typedState(el: { value: string; defaultValue: string; autocomplete: string; type: string }): string {
  if (!el.value) return " (empty)"
  if (el.type === "password" || SECRET.test(el.autocomplete) || el.value !== el.defaultValue) return " (filled)"
  return ` = "${el.value.slice(0, 60)}"`
}
