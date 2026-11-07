/** The places an answer points at on the page, in the order it mentions them. */

import type { Pointer } from "@ext/page/highlight"

const QUOTE = /[“"]([^”"\n]{6,300})[”"]/g
/** A ref as the page text writes it, `[name](e12)`, or bare in brackets: `(e12)`, `[e12]`. */
const REF = /[([](e\d{1,6})[)\]]/g

export function pointers(answer: string, limit = 8): Pointer[] {
  const found: { at: number; p: Pointer; key: string }[] = []
  for (const m of answer.matchAll(QUOTE)) found.push({ at: m.index ?? 0, p: { quote: m[1].trim() }, key: `q:${m[1].trim().toLowerCase()}` })
  for (const m of answer.matchAll(REF)) found.push({ at: m.index ?? 0, p: { ref: m[1] }, key: `r:${m[1]}` })
  const seen = new Set<string>()
  return found.sort((a, b) => a.at - b.at).filter((f) => !seen.has(f.key) && seen.add(f.key)).slice(0, limit).map((f) => f.p)
}

/** "find…", "where is…", "show me…": the user wants to be taken there, not only told. */
export const wantsToGo = (question: string) => /^\s*(find|where|locate|show me|take me|go to|point|highlight)\b/i.test(question)
