import { describe, expect, it } from "vitest"
import { icon } from "@/app/favicon"

describe("favicon", () => {
  it("is the plain mark when idle and carries the state's dot otherwise", () => {
    const svg = (href: string) => decodeURIComponent(href.replace("data:image/svg+xml,", ""))
    expect(svg(icon(null))).not.toContain("circle")
    expect(svg(icon("ask"))).toContain("#f59e0b")
    expect(svg(icon("run", true))).toContain("opacity='0.35'")
  })
})
