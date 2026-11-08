import { describe, expect, it } from "vitest"

import { typedState } from "./page/read"
import { samePlace } from "./shared/settings"

describe("pairing only with the Atlas the extension is set to", () => {
  it("accepts the address it is set to, written either way", () => {
    expect(samePlace("http://127.0.0.1:8000", "http://127.0.0.1:8000/")).toBe(true)
  })
  it("refuses another local port: a page there could run its own server", () => {
    expect(samePlace("http://127.0.0.1:8000", "http://127.0.0.1:3000")).toBe(false)
    expect(samePlace("http://127.0.0.1:8000", "http://localhost:8000")).toBe(false)
  })
  it("refuses what is not an address", () => {
    expect(samePlace("http://127.0.0.1:8000", "not a url")).toBe(false)
  })
})

describe("what the user typed into a field never reaches the model", () => {
  const field = (value: string, defaultValue = "", autocomplete = "", type = "text") =>
    ({ value, defaultValue, autocomplete, type })

  it("says a typed field is filled, not what it holds", () => {
    expect(typedState(field("4111 1111 1111 1111"))).toBe(" (filled)")
    expect(typedState(field("483920"))).toBe(" (filled)")
  })
  it("shows a value the page itself put there", () => {
    expect(typedState(field("Mumbai", "Mumbai"))).toBe(' = "Mumbai"')
  })
  it("never shows a one-time code or card field, even a prefilled one", () => {
    expect(typedState(field("483920", "483920", "one-time-code"))).toBe(" (filled)")
    expect(typedState(field("4111", "4111", "cc-number"))).toBe(" (filled)")
  })
  it("never shows a password", () => {
    expect(typedState(field("hunter2", "hunter2", "", "password"))).toBe(" (filled)")
  })
  it("says an empty field is empty", () => {
    expect(typedState(field(""))).toBe(" (empty)")
  })
})
