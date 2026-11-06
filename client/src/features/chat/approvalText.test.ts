import { describe, expect, it } from "vitest"
import type { Part } from "@/api/types"
import { question } from "@/features/chat/approvalText"

const ask = (command: string, request: "access" | "tool" | "install" | "page" = "access"): Extract<Part, { kind: "approval" }> =>
  ({ kind: "approval", id: "1", request, command, status: "pending", expires_at: 0 })

describe("approval questions", () => {
  it("names the file for file operations, keeping the path a detail", () => {
    expect(question(ask("create C:\\Work\\Reports\\invoices.xlsx"))).toEqual(
      { title: "OK to save invoices.xlsx in Reports?", showCommand: false })
    expect(question(ask("delete (to the Recycle Bin) C:\\Users\\me\\Docs\\old.pdf")).title).toBe(
      "OK to delete old.pdf? It goes to the Recycle Bin.")
  })

  it("always shows what runs: commands, installs, tools, and anything after outside content", () => {
    expect(question(ask("rm -rf build", "tool")).showCommand).toBe(true)
    expect(question(ask("pip install x", "install")).showCommand).toBe(true)
    expect(question(ask('web_search {"query": "x"}', "tool"))).toEqual({ title: "OK to search the web?", showCommand: true })
    expect(question(ask("create C:\\Work\\x.txt", "page")).showCommand).toBe(true)
  })
})
