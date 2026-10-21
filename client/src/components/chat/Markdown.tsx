/**
 * Markdown, rendered block by block.
 *
 * Re-parsing a whole answer on every frame is the expensive part of streaming:
 * a long reply with code is re-tokenised and re-highlighted from the top for
 * every new word. So the text is split into top-level blocks (paragraphs,
 * lists, fenced code), each block is a memoised component keyed by its own
 * text, and while streaming only the last block -- the one still growing --
 * ever re-renders. Blocks are never split inside a fenced code block.
 */

import React, { memo, useMemo, useState } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import rehypeHighlight from "rehype-highlight"
import rehypeKatex from "rehype-katex"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import { Check, Copy } from "lucide-react"

import "katex/dist/katex.min.css"

const remarkPlugins = [remarkGfm, remarkMath]
const rehypePlugins = [[rehypeHighlight, { detect: true, ignoreMissing: true }], rehypeKatex] as never

/** Split at blank lines that are not inside a ``` fence. */
function splitBlocks(text: string): string[] {
  const lines = text.split("\n")
  const blocks: string[] = []
  let current: string[] = []
  let fence: string | null = null
  for (const line of lines) {
    const marker = /^\s*(```+|~~~+)/.exec(line)?.[1]
    if (marker) {
      if (fence === null) fence = marker
      else if (marker.startsWith(fence[0]) && marker.length >= fence.length) fence = null
    }
    if (fence === null && line.trim() === "" && current.length) {
      // A list keeps going across a blank line if the next item continues it;
      // splitting there costs nothing visible, so keep the rule simple.
      blocks.push(current.join("\n"))
      current = []
      continue
    }
    current.push(line)
  }
  if (current.length) blocks.push(current.join("\n"))
  return blocks
}

function CodeBlock({ children, className }: { children?: React.ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false)
  const language = /language-(\S+)/.exec(className ?? "")?.[1]
  const ref = React.useRef<HTMLElement>(null)
  return (
    <div className="code-block group/code relative my-3 overflow-hidden rounded-lg border bg-code text-code-foreground">
      <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-1 text-xs text-muted-foreground">
        <span className="font-mono">{language ?? "text"}</span>
        <button
          type="button"
          className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-background hover:text-foreground"
          onClick={() => {
            void navigator.clipboard.writeText(ref.current?.innerText ?? "")
            setCopied(true)
            setTimeout(() => setCopied(false), 1200)
          }}
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-[13px] leading-relaxed">
        <code ref={ref} className={className}>{children}</code>
      </pre>
    </div>
  )
}

const components: Components = {
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children, node }) => {
    const block = Boolean(className) || String(children).includes("\n") ||
      node?.position?.start.line !== node?.position?.end.line
    if (!block) return <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.875em]">{children}</code>
    return <CodeBlock className={className}>{children}</CodeBlock>
  },
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b bg-muted/60 px-3 py-2 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border-b border-border/60 px-3 py-2">{children}</td>,
}

const Block = memo(function Block({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>
      {text}
    </ReactMarkdown>
  )
})

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => splitBlocks(text), [text])
  return (
    <div className="markdown">
      {blocks.map((block, i) => (
        // Index keys are right here: blocks only ever grow at the end.
        <Block key={i} text={block} />
      ))}
    </div>
  )
})
