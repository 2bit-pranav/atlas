import type { Part } from "@/api/types"
import type { ToolPart } from "@/features/chat/ToolBlock"

/** Parts as they are drawn: a run of consecutive tool calls is one item. With
 * `merge` (the task view), a stretch of work between two texts is one
 * reasoning block followed by its tool calls and approvals: the tools sit in
 * the work panel there, and "Reasoning" repeated per model call read as noise. */
type Item =
  | { tools: ToolPart[]; index: number }
  | { reasoning: string; index: number; last: number }
  | { part: Exclude<Part, ToolPart>; index: number }

export function items(parts: Part[], merge = false): Item[] {
  const out: Item[] = []
  let work: Item[] = []
  const flush = () => { out.push(...work); work = [] }
  parts.forEach((part, index) => {
    const into = merge && part.kind !== "text" && part.kind !== "superseded" ? work : (flush(), out)
    if (merge && part.kind === "reasoning") {
      const r = work.find((w) => "reasoning" in w)
      if (r && "reasoning" in r) { r.reasoning += "\n\n" + part.text; r.last = index }
      else work.unshift({ reasoning: part.text, index, last: index })
      return
    }
    const last = into[into.length - 1]
    const tools = merge ? into.find((w) => "tools" in w) : last && "tools" in last ? last : undefined
    if (part.kind !== "tool") into.push({ part, index })
    else if (tools && "tools" in tools) tools.tools.push(part)
    else into.push({ tools: [part], index })
  })
  flush()
  return out
}
