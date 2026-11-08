/**
 * Google Forms. Its questions are not form fields: a choice is a div with
 * `role="radio"` / `"checkbox"`, a dropdown a `role="listbox"`, each question a
 * `role="listitem"` titled by its `role="heading"`. Read from those roles, set
 * the way a person would (typing fires input events; a choice is clicked; a
 * dropdown is opened, then its option clicked), and checked afterwards: an
 * answer that did not take is reported, never assumed.
 *
 * Only the section on screen: a form with several sections is filled one at a
 * time, the user pressing Next. Submit is never pressed.
 */

export type GKind = "text" | "textarea" | "date" | "radio" | "checkbox" | "dropdown"

export interface GQuestion {
  item: HTMLElement
  kind: GKind
  label: string
  required: boolean
  options: string[]
  input?: HTMLInputElement | HTMLTextAreaElement
}

export const isGoogleForm = (href = location.href) => {
  try {
    const url = new URL(href)
    return url.hostname === "docs.google.com" && /^\/forms\/(u\/\d+\/)?d\//.test(url.pathname)
  } catch {
    return false
  }
}

const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim()
const optionOf = (el: Element) => clean(el.getAttribute("data-value") ?? el.getAttribute("data-answer-value") ?? el.getAttribute("aria-label") ?? el.textContent)
const OTHER = "__other_option__"

/** The questions of the section on screen. Grids and file uploads are left out (not filled). */
export function questions(root: ParentNode = document): GQuestion[] {
  const out: GQuestion[] = []
  for (const item of Array.from(root.querySelectorAll<HTMLElement>('[role="listitem"]'))) {
    const heading = item.querySelector('[role="heading"]')
    const label = clean(heading?.textContent).replace(/\s*\*$/, "")
    if (!label) continue
    const required = Boolean(item.querySelector('[aria-label="Required question"]')) || /\*\s*$/.test(clean(heading?.textContent))
    if (item.querySelectorAll('[role="radiogroup"]').length > 1) continue   // a grid
    const radios = Array.from(item.querySelectorAll('[role="radio"]')).filter((r) => r.getAttribute("data-value") !== OTHER)
    const boxes = Array.from(item.querySelectorAll('[role="checkbox"]')).filter((r) => optionOf(r) !== OTHER)
    const listbox = item.querySelector('[role="listbox"]')
    const area = item.querySelector("textarea")
    const input = item.querySelector<HTMLInputElement>('input[type="text"], input[type="email"], input[type="number"], input[type="url"], input[type="tel"], input[type="date"]')
    if (radios.length) out.push({ item, kind: "radio", label, required, options: radios.map(optionOf).filter(Boolean) })
    else if (boxes.length) out.push({ item, kind: "checkbox", label, required, options: boxes.map(optionOf).filter(Boolean) })
    else if (listbox) out.push({ item, kind: "dropdown", label, required,
                                 options: Array.from(listbox.querySelectorAll('[role="option"]')).map(optionOf).filter((o) => o && o !== "Choose") })
    else if (area) out.push({ item, kind: "textarea", label, required, options: [], input: area })
    else if (input) out.push({ item, kind: input.type === "date" ? "date" : "text", label, required, options: [], input })
  }
  return out
}

const same = (a: string, b: string) => clean(a).toLowerCase() === clean(b).toLowerCase()
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Type a value the way a person would, so the form's own scripts see it. */
export function typeValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  el.focus()
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, value)
  el.dispatchEvent(new Event("input", { bubbles: true }))
  el.dispatchEvent(new Event("change", { bubbles: true }))
  el.blur()
}

const choices = (q: GQuestion, role: string) =>
  Array.from(q.item.querySelectorAll<HTMLElement>(`[role="${role}"]`)).filter((r) => optionOf(r) !== OTHER)

/** Answer one question. `value` is an option, a text, or for checkboxes options one per line. */
export async function answer(q: GQuestion, value: string): Promise<void> {
  if (q.input) return typeValue(q.input, value)
  if (q.kind === "radio") {
    const pick = choices(q, "radio").find((r) => same(optionOf(r), value))
    if (pick && pick.getAttribute("aria-checked") !== "true") pick.click()
  } else if (q.kind === "checkbox") {
    for (const want of value.split("\n").filter(Boolean)) {
      const box = choices(q, "checkbox").find((r) => same(optionOf(r), want))
      if (box && box.getAttribute("aria-checked") !== "true") box.click()
    }
  } else if (q.kind === "dropdown") {
    const listbox = q.item.querySelector<HTMLElement>('[role="listbox"]')
    if (!listbox) return
    listbox.click()
    await wait(300)
    // The open list is drawn as a popup; its options carry the same values.
    const option = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]'))
      .filter((o) => same(optionOf(o), value)).at(-1)
    option?.click()
    await wait(300)
  }
}

/** Whether the question now holds `value`: checked after answering, so a miss is reported. */
export function holds(q: GQuestion, value: string): boolean {
  if (q.input) return q.input.value === value
  if (q.kind === "radio") return choices(q, "radio").some((r) => same(optionOf(r), value) && r.getAttribute("aria-checked") === "true")
  if (q.kind === "checkbox")
    return value.split("\n").filter(Boolean).every((v) => choices(q, "checkbox").some((r) => same(optionOf(r), v) && r.getAttribute("aria-checked") === "true"))
  const selected = q.item.querySelector('[role="option"][aria-selected="true"]')
  return selected ? same(optionOf(selected), value) : false
}
