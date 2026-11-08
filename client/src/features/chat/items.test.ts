import { describe, expect, it } from "vitest"
import type { Part } from "@/api/types"
import { items } from "@/features/chat/items"

const tool = (id: string): Part => ({ kind: "tool", id, name: "read_text", args: {}, status: "success", text: "" })
const parts: Part[] = [
  { kind: "reasoning", text: "a" }, tool("1"), { kind: "reasoning", text: "b" }, tool("2"),
  { kind: "reasoning", text: "c" }, { kind: "text", text: "Done." },
]

describe("items", () => {
  it("keeps each reasoning in place in the chat layout", () => {
    expect(items(parts).map((i) => ("reasoning" in i ? "R" : "tools" in i ? `T${i.tools.length}` : i.part.kind)))
      .toEqual(["reasoning", "T1", "reasoning", "T1", "reasoning", "text"])
  })

  it("merges a stretch of work into one reasoning and one tool group in the task view", () => {
    const out = items(parts, true)
    expect(out.map((i) => ("reasoning" in i ? "R" : "tools" in i ? `T${i.tools.length}` : i.part.kind))).toEqual(["R", "T2", "text"])
    expect(out[0]).toMatchObject({ reasoning: "a\n\nb\n\nc", index: 0, last: 4 })
  })
})
