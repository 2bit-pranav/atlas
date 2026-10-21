/**
 * Fill suggestions, on the page: collect a form's fields, preview suggested
 * values over them, and fill them only when the user applies. Never submits.
 *
 * What is sent to Atlas is each field's label, type and options, never what
 * is typed in it. Passwords, one-time codes, card numbers, CVVs and captchas
 * are never collected and never filled.
 */

import { box, button, shadow, toast } from "./overlay"
import { fieldName, visible } from "./page"

export interface Field {
  id: string
  label: string
  type: string
  options?: string[]
  required?: boolean
}

const SECRET = /pass(word)?|otp|one.?time|cvv|cvc|card.?(no|number)|\bpin\b|captcha|security.?code/i
const TYPES = new Set(["text", "email", "tel", "number", "date", "url", "search", "month", "week", "time", "datetime-local", ""])

let fields = new Map<string, HTMLElement | HTMLInputElement[]>()
let preview: { values: Record<string, string>; layer: HTMLDivElement; bar: HTMLDivElement; frame: number } | null = null

function secret(el: Element, label: string): boolean {
  const auto = el.getAttribute("autocomplete") ?? ""
  return auto.startsWith("cc-") || auto.includes("password") || auto === "one-time-code" ||
    SECRET.test(`${label} ${el.getAttribute("name") ?? ""} ${el.id}`)
}

/** The visible, editable fields of the page's forms, with ids for the preview. */
export function formFields(): Field[] {
  fields = new Map()
  const out: Field[] = []
  const radios = new Map<string, HTMLInputElement[]>()
  let n = 0
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("input, select, textarea"))) {
    if (!visible(el) || (el as HTMLInputElement).disabled || (el as HTMLInputElement).readOnly) continue
    if (el instanceof HTMLInputElement) {
      const type = el.type.toLowerCase()
      if (type === "radio") {
        if (el.name) radios.set(el.name, [...(radios.get(el.name) ?? []), el])
        continue
      }
      if (!TYPES.has(type)) continue  // password, hidden, file, checkbox, buttons
    }
    const label = fieldName(el).replace(/\s+/g, " ").trim().slice(0, 120)
    if (!label || secret(el, label)) continue
    const id = `f${++n}`
    fields.set(id, el)
    const field: Field = { id, label, type: el instanceof HTMLSelectElement ? "select" : el instanceof HTMLTextAreaElement ? "textarea" : (el as HTMLInputElement).type || "text" }
    if (el instanceof HTMLSelectElement)
      field.options = Array.from(el.options).map((o) => o.text.trim()).filter(Boolean)
    if (el.hasAttribute("required") || el.getAttribute("aria-required") === "true") field.required = true
    out.push(field)
  }
  for (const [name, group] of radios) {
    const legend = group[0].closest("fieldset")?.querySelector("legend")?.textContent?.trim()
    const label = (legend || group[0].closest("[role=radiogroup]")?.getAttribute("aria-label") || name).replace(/\s+/g, " ").trim()
    if (secret(group[0], label)) continue
    const id = `f${++n}`
    fields.set(id, group)
    out.push({ id, label, type: "radio", options: group.map((r) => fieldName(r).trim() || r.value) })
  }
  return out.slice(0, 60)
}

function rectOf(target: HTMLElement | HTMLInputElement[]): DOMRect {
  return (Array.isArray(target) ? target[0] : target).getBoundingClientRect()
}

/** Show the suggested values over their fields, with Apply / Discard. Nothing is filled yet. */
export function previewFill(values: Record<string, string>): { shown: number } {
  discardFill()
  const ids = Object.keys(values).filter((id) => fields.has(id))
  if (!ids.length) return { shown: 0 }
  const layer = document.createElement("div")
  shadow().appendChild(layer)
  const bar = box(innerWidth / 2 - 170, innerHeight - 64)
  const label = document.createElement("span")
  label.className = "logo"
  label.textContent = `Atlas suggests ${ids.length} value${ids.length === 1 ? "" : "s"}`
  bar.append(label, button("Apply", () => applyFill()), button("Discard", () => discardFill()))
  const draw = () => {
    layer.replaceChildren(...ids.map((id) => {
      const r = rectOf(fields.get(id)!)
      const tag = document.createElement("div")
      tag.style.cssText = `position:fixed;z-index:2147483646;left:${r.left - 2}px;top:${r.top - 2}px;width:${r.width}px;` +
        `height:${r.height}px;border:2px dashed #ca8a04;border-radius:6px;pointer-events:none;`
      const value = document.createElement("div")
      value.textContent = values[id]
      value.style.cssText = "position:absolute;left:0;bottom:100%;margin-bottom:2px;max-width:320px;overflow:hidden;" +
        "text-overflow:ellipsis;white-space:nowrap;background:#fef3c7;color:#713f12;font:11px/1.4 system-ui,sans-serif;" +
        "padding:1px 6px;border-radius:4px;"
      tag.appendChild(value)
      return tag
    }))
    if (preview) preview.frame = requestAnimationFrame(draw)
  }
  preview = { values, layer, bar, frame: 0 }
  draw()
  ;(Array.isArray(fields.get(ids[0])) ? (fields.get(ids[0]) as HTMLInputElement[])[0] : fields.get(ids[0]) as HTMLElement)
    .scrollIntoView({ behavior: "smooth", block: "center" })
  return { shown: ids.length }
}

/** Set a value the way a person typing would, so frameworks (React, Vue) see it. */
function setValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, value)
  el.dispatchEvent(new Event("input", { bubbles: true }))
  el.dispatchEvent(new Event("change", { bubbles: true }))
}

/** Fill the previewed values. Never submits the form. */
export function applyFill(): { filled: number } {
  if (!preview) return { filled: 0 }
  let filled = 0
  for (const [id, value] of Object.entries(preview.values)) {
    const target = fields.get(id)
    if (!target) continue
    if (Array.isArray(target)) {
      const radio = target.find((r) => (fieldName(r).trim() || r.value) === value)
      if (radio) {
        radio.click()
        filled++
      }
    } else if (target instanceof HTMLSelectElement) {
      const option = Array.from(target.options).find((o) => o.text.trim() === value)
      if (option) {
        target.value = option.value
        target.dispatchEvent(new Event("change", { bubbles: true }))
        filled++
      }
    } else {
      setValue(target as HTMLInputElement, value)
      filled++
    }
  }
  discardFill()
  toast(`Filled ${filled} field${filled === 1 ? "" : "s"}. Check them, then submit the form yourself.`, false, 6000)
  return { filled }
}

export function discardFill(): { ok: boolean } {
  if (preview) {
    cancelAnimationFrame(preview.frame)
    preview.layer.remove()
    preview.bar.remove()
    preview = null
  }
  return { ok: true }
}
