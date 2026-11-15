// @vitest-environment jsdom
import { describe, expect, it } from "vitest"
import { seen } from "./read"

/** jsdom has no layout: give an element the box a browser would. */
function field(style: string, box: { x?: number; y?: number; w?: number; h?: number } = {}, wrapStyle = ""): HTMLInputElement {
  const wrap = document.createElement("div")
  wrap.setAttribute("style", wrapStyle)
  const el = document.createElement("input")
  el.setAttribute("style", style)
  wrap.appendChild(el)
  document.body.appendChild(wrap)
  const { x = 20, y = 20, w = 200, h = 30 } = box
  el.getBoundingClientRect = () => ({ left: x, top: y, right: x + w, bottom: y + h, width: w, height: h, x, y, toJSON: () => ({}) })
  return el
}

describe("a field Fill may suggest a value for", () => {
  it("is one a person can see", () => {
    expect(seen(field(""))).toBe(true)
    expect(seen(field("opacity: 0.6"))).toBe(true)
  })

  it("is not one the page keeps out of sight", () => {
    expect(seen(field("opacity: 0"))).toBe(false)
    expect(seen(field("", {}, "opacity: 0.01"))).toBe(false)                    // hidden by what it sits in
    expect(seen(field("", { w: 1, h: 1 }))).toBe(false)                          // a pixel
    expect(seen(field("", { x: -9999 }))).toBe(false)                            // pushed off the page
    expect(seen(field("", { y: -5000 }))).toBe(false)
    expect(seen(field("clip-path: inset(100%)"))).toBe(false)
    expect(seen(field("", {}, "clip: rect(0px, 0px, 0px, 0px); position: absolute"))).toBe(false)
    expect(seen(field("visibility: hidden"))).toBe(false)
    expect(seen(field("display: none"))).toBe(false)
  })
})
