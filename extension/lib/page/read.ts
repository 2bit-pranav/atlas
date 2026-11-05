/** Reading the page for the model: its readable text, and the list of interactive elements. */

import { Readability } from "@mozilla/readability"
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

export function readable(): string {
  const clone = document.cloneNode(true) as Document
  const article = new Readability(clone, { charThreshold: 400 }).parse()
  if (article?.content && (article.textContent ?? "").trim().length > 600) {
    const title = article.title ? `# ${article.title}\n\n` : ""
    return title + turndown.turndown(article.content).replace(/\n{3,}/g, "\n\n").trim()
  }
  return visibleText()
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

// --------------------------------------------------------------- elements --

const ROLES: Record<string, string> = {
  A: "link", BUTTON: "button", SELECT: "combobox", TEXTAREA: "textbox", SUMMARY: "button",
}

function role(el: Element): string {
  const explicit = el.getAttribute("role")
  if (explicit) return explicit
  if (el.tagName === "INPUT") {
    const type = (el as HTMLInputElement).type
    return { checkbox: "checkbox", radio: "radio", submit: "button", button: "button", reset: "button",
             search: "searchbox", range: "slider", file: "file" }[type] ?? "textbox"
  }
  return ROLES[el.tagName] ?? "button"
}

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

function state(el: Element): string {
  if (el instanceof HTMLSelectElement) {
    const options = Array.from(el.options).map((o) => o.text.trim()).filter(Boolean)
    const shown = options.length > 8 ? `${options.slice(0, 3).join(", ")} ... ${options.at(-1)}` : options.join(", ")
    return ` = "${el.selectedOptions[0]?.text.trim() ?? ""}" options: ${shown}`
  }
  if (el instanceof HTMLInputElement) {
    if (el.type === "checkbox" || el.type === "radio") return el.checked ? " (checked)" : ""
    return typedState(el)
  }
  if (el instanceof HTMLTextAreaElement) return typedState(el)
  return ""
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

const INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], " +
  "[role=link], [role=tab], [role=menuitem], [role=checkbox], [role=combobox], [onclick], [tabindex]:not([tabindex='-1'])"

export function elements(limit = 40): string {
  const seen = new Set<string>()
  const groups = new Map<string, string[]>()
  let count = 0
  for (const el of Array.from(document.querySelectorAll(INTERACTIVE))) {
    if (count >= limit) break
    if (!visible(el)) continue
    const label = fieldName(el).replace(/\s+/g, " ").trim().slice(0, 80)
    if (!label) continue
    const line = `${role(el)} "${label}"${state(el)}`
    if (seen.has(line)) continue
    seen.add(line)
    const form = el.closest("form, nav, [role=dialog], [role=menu], header, footer")
    const group = form
      ? `${form.tagName === "FORM" ? "Form" : form.tagName === "NAV" ? "Navigation" : form.getAttribute("role") ?? form.tagName.toLowerCase()}` +
        (form.getAttribute("aria-label") ? ` "${form.getAttribute("aria-label")}"` : "")
      : "Page"
    groups.set(group, [...(groups.get(group) ?? []), line])
    count++
  }
  if (!count) return "No form fields, buttons or links are visible."
  const out = Array.from(groups.entries()).map(([group, lines]) => `${group}\n${lines.map((l) => `  ${l}`).join("\n")}`)
  return out.join("\n") + (count >= limit ? `\n(first ${limit} shown)` : "")
}
