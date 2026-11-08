/** The places an answer points at on the page, in the order it mentions them. */

import type { Pointer } from "@ext/page/highlight"
import { seconds } from "@ext/page/youtube"

const QUOTE = /[“"]([^”"\n]{6,300})[”"]/g
/** A ref as the page text writes it, `[name](e12)`, or bare in brackets: `(e12)`, `[e12]`. */
const REF = /[([](e\d{1,6})[)\]]/g
/** A moment in a video, as answers cite it: [12:34] or [1:02:03]. */
const TIME = /\[(\d{1,2}(?::\d{2}){1,2})\]/g

/**
 * What the answer says about the moment it cites: the sentence (or list item)
 * holding the time, without the times and Markdown. "In this video" lists it
 * under the time: "[4:10] Why layers help" says more than "Video 4:10".
 */
export function about(answer: string, at: number): string {
  const start = answer.lastIndexOf("\n", at) + 1
  const end = answer.indexOf("\n", at)
  let line = answer.slice(start, end < 0 ? answer.length : end)
  // A long line (a paragraph): only the sentence holding the time.
  if (line.length > 140) {
    const pos = at - start
    let offset = 0
    for (const sentence of line.split(/(?<=[.!?])\s+/)) {
      if (pos < offset + sentence.length + 1) {
        line = sentence
        break
      }
      offset += sentence.length + 1
    }
  }
  // "Later, at [12:30], he explains" reads "Later, he explains": the time goes with its "at".
  const text = line.replace(/(?:\s*\b(?:at|around|from|by))?\s*\[(\d{1,2}(?::\d{2}){1,2})\]/gi, "")
    .replace(/,\s*,/g, ",").replace(/\s+([,.;:!?])/g, "$1").replace(/\(\s*\)|\[\s*\]/g, "")
    .replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").replace(/[*_`#>]/g, "")
    .replace(/\s+/g, " ").replace(/^[\s:,–—-]+|[\s:,–—-]+$/g, "").trim()
  return text.length > 110 ? `${text.slice(0, 109)}…` : text
}

export function pointers(answer: string, limit = 8): Pointer[] {
  const found: { at: number; p: Pointer; key: string }[] = []
  for (const m of answer.matchAll(QUOTE)) found.push({ at: m.index ?? 0, p: { quote: m[1].trim() }, key: `q:${m[1].trim().toLowerCase()}` })
  for (const m of answer.matchAll(REF)) found.push({ at: m.index ?? 0, p: { ref: m[1] }, key: `r:${m[1]}` })
  for (const m of answer.matchAll(TIME))
    found.push({ at: m.index ?? 0, p: { time: seconds(m[1]), label: m[1], about: about(answer, m.index ?? 0) }, key: `t:${m[1]}` })
  const seen = new Set<string>()
  return found.sort((a, b) => a.at - b.at).filter((f) => !seen.has(f.key) && seen.add(f.key)).slice(0, limit).map((f) => f.p)
}

/** "find…", "where is…", "show me…": the user wants to be taken there, not only told. */
export const wantsToGo = (question: string) => /^\s*(find|where|locate|show me|take me|go to|point|highlight)\b/i.test(question)
