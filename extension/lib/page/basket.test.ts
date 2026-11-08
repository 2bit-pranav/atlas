// @vitest-environment jsdom
import { describe, expect, it } from "vitest"
import { accepts, uploadField } from "./basket"

describe("dropping a basket card", () => {
  it("finds the upload field a drop means", () => {
    document.body.innerHTML = `
      <div id="zone1"><span id="inside">Drop here</span><input type="file" id="own" hidden></div>
      <label id="lab" for="cv">Upload resume</label><input type="file" id="cv" style="display:none">
      <div id="both"><input type="file" id="a"><input type="file" id="b"></div>
      <div id="bare">A zone with no field of its own</div>`
    const by = (id: string) => document.getElementById(id)
    expect(uploadField(by("inside"))?.id).toBe("own")          // a drop zone's own hidden field
    expect(uploadField(by("lab"))?.id).toBe("cv")              // a styled label's field
    expect(uploadField(by("both"))).toBeNull()                 // two fields: not guessed
    expect(uploadField(by("bare"))).toBeNull()                 // never some other field on the page
  })

  it("checks a file against what the field accepts", () => {
    const pdf = { name: "Resume_2026.pdf", type: "application/pdf" }
    expect(accepts(".pdf,.docx", pdf)).toBe(true)
    expect(accepts("image/*", pdf)).toBe(false)
    expect(accepts("image/*", { name: "me.JPG", type: "image/jpeg" })).toBe(true)
    expect(accepts("application/pdf", pdf)).toBe(true)
  })
})
