import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", () => ({ answerCall: vi.fn(() => Promise.resolve()) }))

import * as api from "@/lib/api"
import { atlas } from "@/lib/store"

const run = { id: "run-1", chat_id: "chat-1", turn_id: "turn-1" }
const event = { id: "call-1", op: "read", args: { view: "text" } }
// `clientCall` is private: these tests drive it the way the event stream does.
const clientCall = (atlas as unknown as { clientCall: (r: typeof run, e: typeof event) => void }).clientCall.bind(atlas)
const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

describe("client calls (the extension's page operations)", () => {
  beforeEach(() => {
    vi.mocked(api.answerCall).mockClear()
    atlas.onClientCall = null
  })

  it("are left to the window that can reach the page", async () => {
    // B4: a web UI tab on the same chat answered first, with an error,
    // so page_read failed even though the side panel was open.
    clientCall(run, event)
    await settle()
    expect(api.answerCall).not.toHaveBeenCalled()
  })

  it("are answered by the window with a page handler", async () => {
    atlas.onClientCall = async (op, args) => ({ op, args, content: "page text" })
    clientCall(run, event)
    await settle()
    expect(api.answerCall).toHaveBeenCalledWith("run-1", "call-1", { op: "read", args: { view: "text" }, content: "page text" })
  })

  it("report a handler's failure as an error result", async () => {
    atlas.onClientCall = async () => { throw new Error("tab closed") }
    clientCall(run, event)
    await settle()
    expect(api.answerCall).toHaveBeenCalledWith("run-1", "call-1", { error: "tab closed" })
  })
})
