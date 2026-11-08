// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest"
import { answer, holds, isGoogleForm, questions } from "./gforms"

/** A Google Form as its page builds one: questions as list items, choices as divs with roles. */
const FORM = `
  <form><div role="list">
    <div role="listitem"><div role="heading">Full name <span aria-label="Required question">*</span></div>
      <input type="text" aria-labelledby="x"></div>
    <div role="listitem"><div role="heading">Branch</div>
      <div role="radiogroup"><div role="radio" data-value="CSE" aria-checked="false"></div>
      <div role="radio" data-value="IT" aria-checked="false"></div><div role="radio" data-value="__other_option__"></div></div></div>
    <div role="listitem"><div role="heading">Workshops</div>
      <div role="checkbox" data-answer-value="AI" aria-checked="false"></div><div role="checkbox" data-answer-value="Cloud" aria-checked="false"></div></div>
    <div role="listitem"><div role="heading">Grid</div><div role="radiogroup"></div><div role="radiogroup"></div></div>
  </div></form>`

describe("Google Forms", () => {
  beforeEach(() => {
    document.body.innerHTML = FORM
    // Clicking a choice toggles it, as the form's own scripts do.
    document.querySelectorAll('[role="radio"]').forEach((r) => r.addEventListener("click", () => {
      document.querySelectorAll('[role="radio"]').forEach((o) => o.setAttribute("aria-checked", "false"))
      r.setAttribute("aria-checked", "true")
    }))
    document.querySelectorAll('[role="checkbox"]').forEach((c) => c.addEventListener("click", () =>
      c.setAttribute("aria-checked", c.getAttribute("aria-checked") === "true" ? "false" : "true")))
  })

  it("knows a form by its address", () => {
    expect(isGoogleForm("https://docs.google.com/forms/d/e/1FAIpQL/viewform")).toBe(true)
    expect(isGoogleForm("https://docs.google.com/forms/u/0/d/abc/viewform")).toBe(true)
    expect(isGoogleForm("https://docs.google.com/document/d/abc/edit")).toBe(false)
  })

  it("reads each question with its kind and options, leaving out grids and Other", () => {
    expect(questions().map((q) => [q.label, q.kind, q.options, q.required])).toEqual([
      ["Full name", "text", [], true], ["Branch", "radio", ["CSE", "IT"], false], ["Workshops", "checkbox", ["AI", "Cloud"], false],
    ])
  })

  it("answers as a person would, and checks that each answer took", async () => {
    const [name, branch, workshops] = questions()
    await answer(name, "Pranav")
    await answer(branch, "it")
    await answer(workshops, "AI\nCloud")
    expect([holds(name, "Pranav"), holds(branch, "IT"), holds(workshops, "AI\nCloud")]).toEqual([true, true, true])
    expect(holds(branch, "CSE")).toBe(false)
  })
})
