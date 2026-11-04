import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Reasoning } from "@/features/chat/Reasoning"
import { ToolGroup, type ToolPart } from "@/features/chat/ToolBlock"

const call = (name: string, status: ToolPart["status"], path: string): ToolPart =>
  ({ kind: "tool", id: `${name}-${path}`, name, status, args: { path }, text: "the output" }) as ToolPart

describe("tool calls", () => {
  it("fold a run of calls into one summary line, closed, with failures visible", () => {
    const html = renderToStaticMarkup(
      <ToolGroup defaultOpen={false} parts={[call("read_pdf", "success", "a.pdf"), call("read_pdf", "error", "b.pdf"),
                                               call("read_docx", "success", "c.docx")]} />)
    expect(html).toContain("3 tool calls")
    expect(html).toContain("read_pdf, read_docx")
    expect(html).toContain("1 failed")
    expect(html).not.toContain("a.pdf")          // the calls themselves only when opened
    expect(html).not.toContain("the output")
  })

  it("show one call as its own line, with what it acted on", () => {
    const html = renderToStaticMarkup(<ToolGroup defaultOpen={false} parts={[call("read_text", "success", "notes.txt")]} />)
    expect(html).toContain("read_text")
    expect(html).toContain("notes.txt")
    expect(html).not.toContain("tool calls")
    expect(html).not.toContain("the output")
  })
})

describe("reasoning", () => {
  it("stays collapsed while it streams", () => {
    const html = renderToStaticMarkup(<Reasoning text="thinking about it" streaming interrupted={false} defaultOpen={false} />)
    expect(html).toContain("Reasoning...")
    expect(html).not.toContain("thinking about it")
  })
})
