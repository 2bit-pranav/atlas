/** An approval card's question in plain words (pure: tested without a browser). */

import type { Part } from "@/api/types"

type ApprovalPart = Extract<Part, { kind: "approval" }>

const base = (p: string) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p
const folder = (p: string) => base(p.replace(/[\\/][^\\/]*$/, ""))

/**
 * The question in plain words, and whether the exact command must stay in view.
 *
 * A file operation names its file and folder in the question, so the full path
 * is a detail. A command, an install, or anything after outside content keeps
 * its exact text on the card: a summary there could hide what is approved.
 */
export function question(part: ApprovalPart): { title: string; showCommand: boolean } {
  const line = part.command.split("\n")[0]
  if (part.request === "page") return { title: "This task read outside content. OK to run this?", showCommand: true }
  if (part.request === "install") return { title: "OK to install this?", showCommand: true }
  const file = /^(read|create|change|delete \(to the Recycle Bin\)) (.+)$/.exec(line)
  if (file) {
    const [, verb, path] = file
    const name = base(path)
    if (verb === "create") return { title: `OK to save ${name} in ${folder(path)}?`, showCommand: false }
    if (verb === "change") return { title: `OK to change ${name}?`, showCommand: false }
    if (verb === "read") return { title: `OK to read ${name}? It is outside your folders.`, showCommand: false }
    return { title: `OK to delete ${name}? It goes to the Recycle Bin.`, showCommand: false }
  }
  const tool = line.split(" ")[0]
  if (tool === "web_search") return { title: "OK to search the web?", showCommand: true }
  if (tool === "read_url") return { title: "OK to read a web page?", showCommand: true }
  if (part.request === "tool" && /^[a-z0-9_-]+$/i.test(tool) && tool !== "shell") {
    return { title: `OK to use ${tool.replace(/_/g, " ")}?`, showCommand: true }
  }
  return { title: "OK to run a command?", showCommand: true }
}
