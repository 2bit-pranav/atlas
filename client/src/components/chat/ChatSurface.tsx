/**
 * The chat surface.
 *
 * Built on assistant-ui's primitives with generous padding, rich markdown rendering,
 * flattened source chips, user-side prompt editing, and isolated live typing indicators.
 */

import React from "react"
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react"
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown"
import remarkGfm from "remark-gfm"
import { FileSpreadsheet, FileText, Loader2, Pencil } from "lucide-react"

import { DataRenderers } from "@/components/chat/Reasoning"
import { ToolCard } from "@/components/chat/ToolCard"
import { WelcomeScreen } from "@/components/chat/WelcomeScreen"
import { Composer } from "@/components/chat/Composer"
import { atlas, useAtlas, type AtlasMessage } from "@/services/atlasStore"
import { useAtlasRuntime } from "@/services/atlasRuntime"
import { cn } from "@/lib/utils"

function turnOf(messageId: string): string | null {
  const match = /^(user|assistant):(.+)$/.exec(messageId)
  return match ? match[2] : null
}

/**
 * Enhanced Markdown renderer with proper spacing, readable typography,
 * code blocks, and full table support.
 */
const Markdown: React.FC = () => (
  <MarkdownTextPrimitive
    remarkPlugins={[remarkGfm]}
    components={{
      h1: ({ children }) => (
        <h1 className="text-xl font-bold tracking-tight mt-6 mb-3 text-foreground">
          {children}
        </h1>
      ),
      h2: ({ children }) => (
        <h2 className="text-lg font-semibold tracking-tight mt-5 mb-2.5 text-foreground">
          {children}
        </h2>
      ),
      h3: ({ children }) => (
        <h3 className="text-base font-semibold tracking-tight mt-4 mb-2 text-foreground">
          {children}
        </h3>
      ),
      p: ({ children }) => (
        <p className="text-[15px] leading-7 mb-3.5 last:mb-0 text-foreground/95">
          {children}
        </p>
      ),
      ul: ({ children }) => (
        <ul className="list-disc pl-6 my-3 space-y-1.5 text-[15px] leading-7 text-foreground/95">
          {children}
        </ul>
      ),
      ol: ({ children }) => (
        <ol className="list-decimal pl-6 my-3 space-y-1.5 text-[15px] leading-7 text-foreground/95">
          {children}
        </ol>
      ),
      li: ({ children }) => <li className="leading-7">{children}</li>,
      code: ({ children, className }) => {
        const isInline = !className
        if (isInline) {
          return (
            <code className="px-1.5 py-0.5 rounded-md bg-muted font-mono text-[13px] text-foreground border border-border/50">
              {children}
            </code>
          )
        }
        return (
          <pre className="p-4 rounded-xl bg-muted/60 border border-border/80 overflow-x-auto font-mono text-xs my-4 leading-relaxed text-foreground">
            <code>{children}</code>
          </pre>
        )
      },
      table: ({ children }) => (
        <div className="overflow-x-auto my-4 rounded-xl border border-border/80 shadow-xs">
          <table className="w-full text-left text-sm border-collapse">
            {children}
          </table>
        </div>
      ),
      th: ({ children }) => (
        <th className="bg-muted/70 px-4 py-2.5 font-semibold text-foreground border-b border-border/80 text-xs uppercase tracking-wider">
          {children}
        </th>
      ),
      td: ({ children }) => (
        <td className="px-4 py-2.5 border-b border-border/40 text-foreground/90 text-sm">
          {children}
        </td>
      ),
      blockquote: ({ children }) => (
        <blockquote className="border-l-4 border-primary/40 pl-4 py-1 italic my-3 text-muted-foreground">
          {children}
        </blockquote>
      ),
    }}
  />
)

export const ChatSurface: React.FC = () => {
  const runtime = useAtlasRuntime()
  const state = useAtlas()

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <DataRenderers />

      <ThreadPrimitive.Root className="flex h-full flex-col">
        <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 py-8 sm:px-8">
          <div className="mx-auto w-full max-w-3xl pb-40">
            <ThreadPrimitive.Empty>
              <WelcomeScreen
                onSend={(text, files) => atlas.send(text, files)}
                isLoading={state.busy}
              />
            </ThreadPrimitive.Empty>

            <ThreadPrimitive.Messages
              components={{ UserMessage: UserRow, AssistantMessage: AssistantRow }}
            />

            <ThreadPrimitive.ScrollToBottom />
          </div>
        </ThreadPrimitive.Viewport>

        <div className="pointer-events-none absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background/95 to-transparent p-4 sm:p-6">
          <div className="pointer-events-auto mx-auto w-full max-w-3xl">
            <Composer />
          </div>
        </div>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  )
}

// ------------------------------------------------------------------ rows --

/**
 * User message row: includes generous padding, the Edit button placed near
 * the user's prompt (which re-populates composer and staged attachments),
 * and flattened source chips.
 */
const UserRow: React.FC = () => {
  const messageId = useAuiState((s) => s.message.id)
  const turnId = messageId ? turnOf(messageId) : null
  const state = useAtlas()
  const turn = state.turns.find((t) => t.id === turnId)
  const files = turn?.files ?? []
  const userText = turn?.user_text ?? ""

  const handleEdit = () => {
    if (!turnId) return
    atlas.populateComposer(userText, files)
  }

  return (
    <MessagePrimitive.Root className="group mb-8 flex flex-col items-end gap-2.5">
      <div className="flex items-start gap-2 max-w-[85%]">
        {/* Edit button placed near user's message */}
        <button
          type="button"
          onClick={handleEdit}
          disabled={state.busy}
          title="Edit prompt and re-stage attachments"
          className="opacity-0 group-hover:opacity-100 transition-opacity mt-2 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>

        {/* User Prompt Bubble */}
        <div className="rounded-2xl md:rounded-3xl bg-muted/80 text-foreground px-5 py-3 text-[15px] leading-relaxed border border-border/50 shadow-xs">
          <MessagePrimitive.Parts
            components={{
              Text: ({ text }) => (
                <span className="whitespace-pre-wrap">{text}</span>
              ),
            }}
          />
        </div>
      </div>

      {/* Flattened Source Chips for attached files below prompt (matching Screenshot 3) */}
      {files.length > 0 && (
        <div className="flex flex-wrap items-center justify-end gap-2 max-w-[90%] pt-0.5">
          {files.map((file) => (
            <div
              key={file.path}
              className="flex items-center gap-2.5 px-3 py-2 rounded-xl border border-border/80 bg-background/90 shadow-2xs text-left"
            >
              <div className="flex h-6 w-6 items-center justify-center rounded-md bg-muted/70 text-primary">
                {file.name.endsWith(".csv") ? (
                  <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                ) : (
                  <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                )}
              </div>
              <div className="flex flex-col min-w-0 pr-1">
                <span className="text-xs font-medium text-foreground truncate max-w-[160px] sm:max-w-[200px]">
                  {file.name}
                </span>
                <span className="text-[10px] text-muted-foreground font-mono">
                  Source
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </MessagePrimitive.Root>
  )
}

/**
 * Assistant row with spacious typography, tools, reasoning, and a typing indicator
 * that is strictly scoped to the active last message.
 */
const AssistantRow: React.FC = () => (
  <MessagePrimitive.Root className="mb-8 flex flex-col items-start w-full">
    <div className="w-full max-w-full text-[15px] leading-relaxed text-foreground space-y-3">
      <MessagePrimitive.Parts
        components={{
          Text: Markdown,
          tools: {
            Fallback: ({ toolName, args, result, isError }) => (
              <ToolCard
                name={String(toolName ?? "tool")}
                args={args}
                status={isError ? "error" : result ? "success" : "running"}
                text={resultText(result)}
              />
            ),
          },
        }}
      />
      <TypingIndicator />
    </div>
  </MessagePrimitive.Root>
)

/**
 * The typing cursor while the answer streams.
 * Strictly scoped to `MessagePrimitive.If last` so previous completed rows
 * will NEVER display a spinner!
 */
const TypingIndicator: React.FC = () => (
  <MessagePrimitive.If last>
    <ThreadPrimitive.If running>
      <div className="flex items-center gap-2 mt-3 text-muted-foreground text-xs font-medium">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        <span>Atlas is working...</span>
      </div>
    </ThreadPrimitive.If>
  </MessagePrimitive.If>
)

// ---------------------------------------------------------------- helper --

function resultText(result: unknown): string {
  if (result === undefined || result === null) return ""

  let value: unknown = result
  if (typeof value === "object" && value !== null && "text" in value) {
    value = (value as { text: unknown }).text
  }
  if (typeof value !== "string") {
    try {
      value = JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }

  const text = value as string
  try {
    const parsed = JSON.parse(text) as Record<string, unknown>
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.output === "string" &&
      ("exit_code" in parsed || "error" in parsed)
    ) {
      const out = parsed.output as string
      const err = typeof parsed.error === "string" ? parsed.error : ""
      return [out.trim(), err.trim()].filter(Boolean).join("\n")
    }
  } catch {
    /* not JSON; it is already the text we want */
  }
  return text
}

export type { AtlasMessage }
export { cn }