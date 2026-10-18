/**
 * The empty state.
 *
 * The previous version offered a model dropdown listing Llama 3.3 70B, Qwen,
 * Mistral and DeepSeek. None of those files exist on this machine; the only
 * model Atlas has is the one in `settings.json`. A picker that lists models
 * you do not have is worse than no picker, because it makes the app look
 * configured when it is not.
 *
 * So this shows the real model, read from settings, and nothing that could be
 * picked.
 */

import React from "react"
import { Cpu, FileSpreadsheet, FileText } from "lucide-react"

import { useAtlas } from "@/services/atlasStore"
import type { ChatFile } from "@/types/api"

interface WelcomeScreenProps {
  onSend: (text: string, files?: ChatFile[]) => void
  isLoading: boolean
}

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
  onSend,
  isLoading,
}) => {
  const { settings } = useAtlas()

  const modelPath = (settings?.values["model.path"] as string) ?? ""
  const contextSize = settings?.values["model.context_size"]

  const suggestions = [
    "Summarise this spreadsheet and tell me which month did best.",
    "What is in this document? Give me the key dates and decisions.",
  ]

  const pick = (suggestion: string) => {
    if (!isLoading) onSend(suggestion)
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center justify-center py-16 text-center">
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-foreground text-background">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          className="h-6 w-6"
        >
          <circle cx="12" cy="12" r="7" />
          <path d="M12 9v6" />
          <path d="M9 12h6" />
        </svg>
      </div>

      <h1 className="text-xl font-semibold tracking-tight">Atlas</h1>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">
        Runs a local model that reads your files through skills. Attach a
        spreadsheet or a document and ask about it.
      </p>

      {/* The one real model, read from settings. Not a picker. */}
      <div className="mt-4 flex items-center gap-2 rounded-full border border-border/60 bg-muted/40 px-3 py-1.5 text-[11px]">
        <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="max-w-xs truncate font-mono">
          {modelPath ? modelPath.split(/[\\/]/).pop() : "no model configured"}
        </span>
        {typeof contextSize === "number" && (
          <span className="text-muted-foreground">
            {contextSize.toLocaleString()} ctx
          </span>
        )}
      </div>

      {settings && settings.skills.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
          {settings.skills.map((skill) => (
            <span
              key={skill.name}
              className="rounded-full border border-border/60 bg-muted/30 px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
            >
              {skill.name}
            </span>
          ))}
        </div>
      )}

      {/* Clicking one sends it. There is deliberately no input box here: the
          composer below is always on screen, and a second text field on the
          empty state meant two ways to type the same message with different
          behaviour -- one of which silently ignored the attachments staged on
          the other. */}
      <div className="mt-8 w-full space-y-1.5">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            onClick={() => pick(suggestion)}
            disabled={isLoading}
            className="flex w-full items-center gap-2.5 rounded-xl border border-border/60 px-3 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            {suggestion.includes("spreadsheet") ? (
              <FileSpreadsheet className="h-4 w-4 shrink-0" />
            ) : (
              <FileText className="h-4 w-4 shrink-0" />
            )}
            {suggestion}
          </button>
        ))}
      </div>

      <p className="mt-3 text-[10px] text-muted-foreground">
        Type below, or attach a file with the paperclip.
      </p>
    </div>
  )
}