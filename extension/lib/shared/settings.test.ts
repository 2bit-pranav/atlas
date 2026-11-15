import { beforeEach, describe, expect, it, vi } from "vitest"
import { loadSettings, pageSettings, saveSettings } from "./settings"

describe("the pairing token", () => {
  let stored: Record<string, unknown>
  beforeEach(() => {
    stored = {}
    vi.stubGlobal("browser", {
      storage: { local: {
        get: async (keys: string[]) => Object.fromEntries(keys.filter((k) => k in stored).map((k) => [k, stored[k]])),
        set: async (items: Record<string, unknown>) => void Object.assign(stored, items),
      } },
    })
  })

  it("is kept under its own key, apart from what a content script is given", async () => {
    await saveSettings({ token: "tok-123", neverRead: ["bank.example"] })
    expect(stored.pairing).toEqual({ token: "tok-123" })
    expect(JSON.stringify(stored.settings)).not.toContain("tok-123")
    const loaded = await loadSettings()
    expect(loaded.token).toBe("tok-123")
    expect(pageSettings(loaded)).not.toHaveProperty("token")
    expect(pageSettings(loaded).neverRead).toEqual(["bank.example"])
  })

  it("moves out of the settings an older version saved it in", async () => {
    stored.settings = { token: "old-tok", base: "http://127.0.0.1:8000" }
    expect((await loadSettings()).token).toBe("old-tok")
    await saveSettings({})
    expect(stored.pairing).toEqual({ token: "old-tok" })
    expect(stored.settings).not.toHaveProperty("token")
  })
})
