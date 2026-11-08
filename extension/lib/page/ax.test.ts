// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest"

import { byRef, outline } from "./ax"
import { cleanTitle, exportUrl, googleTarget } from "./google"
import { around } from "./snapshot"

const PORTAL = `
  <header><nav aria-label="Main"><a href="/">Home</a><a href="/exams">Exams</a><span hidden>Secret menu</span></nav></header>
  <main>
    <h1>Exam results</h1>
    <p>Results for <b>Sem 6</b> are out. <a href="/r.pdf">Download PDF</a></p>
    <ul><li>Revaluation closes 30 June</li><li>Fee: ₹500</li></ul>
    <div aria-hidden="true">tracking pixel text</div>
    <table><caption>Timetable</caption>
      <tr><th>Date</th><th>Course</th></tr><tr><td>12 May</td><td>Embedded</td></tr><tr><td>14 May</td><td>ML</td></tr>
    </table>
    <form aria-label="Revaluation">
      <label for="roll">Roll number</label><input id="roll" value="">
      <label><input type="checkbox" checked> I agree</label>
      <input type="password" aria-label="Password" value="hunter2">
      <div role="button" aria-labelledby="go-label"><span id="go-label">Submit request</span></div>
    </form>
  </main>
  <script>var secret = 1</script>`

describe("the page as an accessibility tree", () => {
  beforeEach(() => { document.body.innerHTML = PORTAL })

  it("keeps the content, headings, lists and tables in order, and the menu as one line", () => {
    const text = outline(document.body)
    expect(text).toContain("# Exam results")
    expect(text).toMatch(/Results for Sem 6 are out\. \[Download PDF\]\(e\d+\)/)
    expect(text).toContain("- Revaluation closes 30 June")
    expect(text).toContain("Table: Timetable")
    expect(text).toContain("| 12 May | Embedded |")
    expect(text).toMatch(/\[(banner|navigation) "Main"\] \[Home\]\(e\d+\) · \[Exams\]\(e\d+\)/)
  })

  it("names fields as a screen reader would, and never shows what was typed", () => {
    const text = outline(document.body)
    expect(text).toMatch(/\[textbox: Roll number \(empty\)\]\(e\d+\)/)
    expect(text).toMatch(/\[checkbox: I agree \(checked\)\]\(e\d+\)/)
    expect(text).toMatch(/\[button: Submit request\]\(e\d+\)/)            // a div named by aria-labelledby
    expect(text).toMatch(/\[textbox: Password \(filled\)\]/)
    expect(text).not.toContain("hunter2")
  })

  it("leaves out hidden content and scripts", () => {
    const text = outline(document.body)
    for (const gone of ["Secret menu", "tracking pixel", "var secret"]) expect(text).not.toContain(gone)
  })

  it("gives an element the same ref every time, and finds it by that ref", () => {
    const first = /\[button: Submit request\]\((e\d+)\)/.exec(outline(document.body))![1]
    const again = /\[button: Submit request\]\((e\d+)\)/.exec(outline(document.body))![1]
    expect(again).toBe(first)
    expect(byRef(first)?.textContent).toBe("Submit request")
  })

  it("lists only what can be pointed at, when asked", () => {
    const text = outline(document.querySelector("main")!, { interactiveOnly: true })
    expect(text.split("\n").every((l) => /^\[.+\]\(e\d+\)$/.test(l))).toBe(true)
    expect(text).not.toContain("Exam results")
  })

  it("stops at the budget and says the page goes on", () => {
    document.body.innerHTML = Array.from({ length: 400 }, (_, i) => `<p>Paragraph ${i} with some words in it.</p>`).join("")
    const text = outline(document.body, { max: 2000 })
    expect(text.length).toBeLessThan(2200)
    expect(text.endsWith("(the page continues)")).toBe(true)
  })

  it("walks open shadow roots", () => {
    document.body.innerHTML = `<div id="host"></div>`
    const root = document.getElementById("host")!.attachShadow({ mode: "open" })
    root.innerHTML = `<p>Inside the component</p><button>Shadow button</button>`
    const text = outline(document.body)
    expect(text).toContain("Inside the component")
    expect(text).toMatch(/\[button: Shadow button\]\(e\d+\)/)
  })

  it("finds the section around a selected passage", () => {
    document.body.innerHTML = `<section id="s"><h2>Attendance</h2><p>A student must have a minimum of 75% attendance.</p></section><p>Other</p>`
    expect(around("a minimum of 75% attendance")?.id).toBe("s")
  })
})

describe("Google apps", () => {
  it("knows each app and file from its address", () => {
    expect(googleTarget("https://docs.google.com/document/d/1AbCdEfGhIjK_lm/edit?tab=t.0")).toEqual({ app: "document", id: "1AbCdEfGhIjK_lm" })
    expect(googleTarget("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjK_lm/edit#gid=42"))
      .toEqual({ app: "spreadsheets", id: "1AbCdEfGhIjK_lm", gid: "42" })
    expect(googleTarget("https://docs.google.com/presentation/d/1AbCdEfGhIjK_lm/edit")?.app).toBe("presentation")
    expect(googleTarget("https://drive.google.com/file/d/1AbCdEfGhIjK_lm/view")).toEqual({ app: "drive-file", id: "1AbCdEfGhIjK_lm" })
    expect(googleTarget("https://docs.google.com/forms/d/1AbCdEfGhIjK_lm/viewform")).toBeNull()
    expect(googleTarget("https://example.com/document/d/1AbCdEfGhIjK_lm")).toBeNull()
  })

  it("reads each through its export, with a fallback", () => {
    const doc = { app: "document" as const, id: "1AbCdEfGhIjK_lm" }
    expect(exportUrl(doc)).toBe("https://docs.google.com/document/d/1AbCdEfGhIjK_lm/export?format=txt")
    expect(exportUrl(doc, true)).toBe("https://docs.google.com/document/d/1AbCdEfGhIjK_lm/mobilebasic")
    expect(exportUrl({ app: "spreadsheets", id: "1AbCdEfGhIjK_lm", gid: "42" })).toContain("gviz/tq?tqx=out:csv&gid=42")
    expect(cleanTitle("Academic calendar 2026 - Google Docs")).toBe("Academic calendar 2026")
  })
})

describe("what an answer points at", () => {
  it("takes quotes and element refs in the order they come, once each", async () => {
    const { pointers, wantsToGo } = await import("./pointers")
    const answer = 'Your result is in the row "Sem V (Regular) · Pass". Download it with [Marksheet](e12), ' +
                   'or see "Sem V (Regular) · Pass" again and the button (e40).'
    expect(pointers(answer)).toEqual([{ quote: "Sem V (Regular) · Pass" }, { ref: "e12" }, { ref: "e40" }])
    expect(pointers('Say "Yes" here')).toEqual([])                           // too short to be a passage
    expect(wantsToGo("find semester V regular")).toBe(true)
    expect(wantsToGo("summarise this page")).toBe(false)
  })

  it("finds a quote exactly, or the passage that says the same, and the element a ref names", async () => {
    const { point } = await import("./highlight")
    document.body.innerHTML = `<h2>Semester-V (Regular) Examination</h2><p>Results are out.</p><a href="/m.pdf">Download marksheet</a>`
    const ref = /\[Download marksheet\]\((e\d+)\)/.exec(outline(document.body))![1]
    const { places } = point([{ quote: "Results are out." }, { quote: "Semester V Regular Examination" }, { ref }, { quote: "nothing like this anywhere at all" }])
    expect(places.map((p) => [p.how, p.kind])).toEqual([["exact", "Text"], ["similar", "Heading"], ["element", "Link"], ["none", "Text"]])
    expect(places[2].href).toContain("/m.pdf")
  })
})

describe("the page's text, as words", () => {
  it("matches a quote exactly across bold and links, without doubled spaces", async () => {
    const { point } = await import("./highlight")
    document.body.innerHTML = `<p>It was established in 1857 as the <b>University of Bombay</b> following a dispatch.</p>` +
      `<p><span>18</span><span>July</span> <span>1857</span></p>`
    const { places } = point([{ quote: "established in 1857 as the University of Bombay following" }, { quote: "18 July 1857" }])
    expect(places.map((p) => p.how)).toEqual(["exact", "exact"])                 // parts shown apart stay apart
    expect(places[0].text).toContain("as the University of Bombay following")
  })
})

