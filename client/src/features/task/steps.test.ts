import { describe, expect, it } from "vitest"
import type { Part } from "@/api/types"
import { downloaded, sources, toSteps, workSummary } from "@/features/task/steps"

const tool = (name: string, args: Record<string, unknown>, text = "", status: "success" | "error" | "running" = "success"): Part =>
  ({ kind: "tool", id: `${name}-${JSON.stringify(args)}`, name, args, status, text })

describe("steps", () => {
  it("groups a run of one tool and names what was read", () => {
    const parts: Part[] = [
      tool("find_files", { query: "invoice", path: "Downloads" }, "3 file(s) found, best first:\n- a"),
      tool("read_pdf", { path: "/c/x/Downloads/invoice-5821.pdf" }),
      tool("read_pdf", { path: "/c/x/Downloads/invoice-5820.pdf" }),
      tool("read_pdf", { path: "/c/x/Downloads/invoice-5819.pdf" }),
      tool("skills", { skill_name: "xlsx" }),
      tool("calculate", { expression: "980 + 2100 + 1240" }, "4320"),
      tool("create_document", { path: "Reports/invoices.xlsx", content: "x" }),
      { kind: "text", text: "Done." },
    ]
    const steps = toSteps(parts, false)
    expect(steps.map((s) => s.label)).toEqual([
      'Searched your folders for "invoice" · 3 found',
      "Read 3 invoices",
      "Loaded the xlsx skill",
      "Worked out 980 + 2100 + 1240 = 4320",
      "Saved invoices.xlsx",
    ])
    expect(steps[2].internal).toBe(true)
    expect(steps[1].detail).toEqual(["read_pdf invoice-5821.pdf", "read_pdf invoice-5820.pdf", "read_pdf invoice-5819.pdf"])
    expect([...downloaded(parts)]).toEqual([])                       // read from the folders: nothing downloaded
    expect([...downloaded([tool("read_pdf", { path: "https://x.org/brief.pdf?v=2" })])]).toEqual(["brief.pdf"])
  })

  it("marks the call an approval holds as waiting, and the answer as being written", () => {
    const waiting = toSteps([tool("create_document", { path: "a.xlsx" }, "", "running"),
                             { kind: "approval", id: "1", command: "create a.xlsx", status: "pending", expires_at: 0 }], true)
    expect(waiting[0].status).toBe("waiting")
    const writing = toSteps([tool("read_text", { path: "notes.txt" }), { kind: "text", text: "The" }], true)
    expect(writing.map((s) => [s.label, s.status])).toEqual([["Read notes.txt", "done"], ["Writing the answer", "running"]])
  })

  it("names mixed files as files and failed saves as failures", () => {
    const steps = toSteps([tool("read_docx", { path: "a.docx" }), tool("read_docx", { path: "budget.docx" }),
                           { kind: "text", text: "x" }, tool("create_document", { path: "r.docx" }, "Error", "error")], false)
    expect(steps.map((s) => [s.label, s.status])).toEqual([["Read 2 files", "done"], ["Could not save r.docx", "error"]])
  })

  it("collects web sources once each", () => {
    const text = "[1] Nobel Prize - nobelprize.org (other, 08 Oct 2024)\n    https://www.nobelprize.org/p\n" +
                 '    "quote"\n[2] Reuters story - reuters.com (news, undated)\n    https://reuters.com/x\n    "q"'
    const found = sources([tool("web_search", { query: "nobel" }, text), tool("read_url", { url: "https://www.nobelprize.org/p" }, "Nobel - x")])
    expect(found.map((s) => s.site)).toEqual(["nobelprize.org", "reuters.com"])
  })

  it("says what did not happen when the user said no", () => {
    const steps = toSteps([tool("delete_file", { path: "C:/x/Documents/Old/Resume 2022.pdf" }, "The user did not allow this", "error"),
                           { kind: "approval", id: "1", command: "delete (to the Recycle Bin) C:/x", status: "denied", expires_at: 0 },
                           { kind: "text", text: "I did not delete it." }], false)
    expect(steps).toMatchObject([{ label: "Did not delete Resume 2022.pdf", status: "error", note: "You said no" }])
  })
})

describe("the work line", () => {
  it("says what was done in one line, and how much more", () => {
    expect(workSummary([])).toBe("Thought it through")
    expect(workSummary(["Read the page again"])).toBe("Read the page again")
    expect(workSummary(["a", "b", "c", "d"])).toBe("a · b · 2 more")
  })
  it("names page searches by what was looked for", () => {
    const steps = toSteps([tool("page_find", { text: "semester V" }, "[Page content…]\n2 passage(s) found and highlighted:")], false)
    expect(steps[0].label).toBe('Searched the page for "semester V" · 2 found')
  })
})
