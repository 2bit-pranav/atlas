/**
 * The composer: text, attachments, drag-and-drop, send, stop.
 */

import React, { useEffect, useRef, useState } from "react"
import { ComposerPrimitive, useAui } from "@assistant-ui/react"
import { ArrowUp, Brain, FileText, Loader2, Paperclip, Square, Upload, X } from "lucide-react"

import { atlas, useAtlas } from "@/services/atlasStore"
import * as api from "@/services/atlasApi"
import { cn } from "@/lib/utils"
import type { ChatFile } from "@/types/api"

export const Composer: React.FC = () => {
  const state = useAtlas()
  const aui = useAui()
  const [uploading, setUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const dragCounter = useRef(0)

  // Listen for draftText populated via "Edit" button on user messages
  useEffect(() => {
    if (state.draftText !== null) {
      aui.composer.setText(state.draftText)
      atlas.clearDraft()
      // Focus textarea
      setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>(
          "textarea[name='input'], textarea"
        )
        if (textarea) {
          textarea.focus()
          textarea.setSelectionRange(textarea.value.length, textarea.value.length)
        }
      }, 50)
    }
  }, [state.draftTimestamp, state.draftText, aui])

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setUploadError(null)
    setUploading(true)
    try {
      const chatId = state.chatId ?? (await atlas.newChat(), atlas.getSnapshot().chatId)
      if (!chatId) throw new Error("could not create a chat to upload into")

      const uploaded: ChatFile[] = []
      for (const file of Array.from(files)) {
        uploaded.push(await api.uploadFile(chatId, file))
      }
      atlas.stageFiles(uploaded)
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "upload failed")
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ""
    }
  }

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current += 1
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true)
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current -= 1
    if (dragCounter.current <= 0) {
      dragCounter.current = 0
      setIsDragging(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current = 0
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await upload(e.dataTransfer.files)
    }
  }

  return (
    <ComposerPrimitive.Root
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        "relative rounded-2xl md:rounded-3xl border border-border/80 bg-background/95 shadow-xl backdrop-blur transition-all",
        isDragging && "border-primary ring-2 ring-primary/30 bg-primary/5"
      )}
    >
      {/* Drag & drop overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-30 flex flex-col items-center justify-center rounded-2xl md:rounded-3xl bg-background/95 border-2 border-dashed border-primary backdrop-blur-sm pointer-events-none">
          <Upload className="h-8 w-8 text-primary animate-bounce mb-1" />
          <span className="text-sm font-medium text-foreground">Drop files here to attach</span>
          <span className="text-xs text-muted-foreground">PDFs, CSVs, text, and code files</span>
        </div>
      )}

      {/* Staged files bar */}
      {state.staged.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border/50 px-4 py-2.5 bg-muted/20 rounded-t-2xl md:rounded-t-3xl">
          <span className="text-[11px] font-medium text-muted-foreground mr-1">
            Attached ({state.staged.length}):
          </span>
          {state.staged.map((file) => (
            <span
              key={file.path}
              className="group flex items-center gap-2 rounded-xl bg-background border border-border/80 px-3 py-1.5 text-xs shadow-xs hover:border-border transition-all"
            >
              <FileText className="h-3.5 w-3.5 text-primary shrink-0" />
              <span className="font-medium text-foreground truncate max-w-[180px] sm:max-w-[220px]">
                {file.name}
              </span>
              <button
                type="button"
                onClick={() => atlas.unstageFile(file.path)}
                title="Remove attachment"
                className="text-muted-foreground hover:text-destructive transition-colors ml-0.5 rounded-full p-0.5"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      {uploadError && (
        <p className="border-b border-destructive/40 bg-destructive/10 px-4 py-2 text-xs text-destructive">
          {uploadError}
        </p>
      )}

      {/* Input area & Controls */}
      <div className="flex items-end gap-2 px-3 py-2.5 sm:px-4 sm:py-3">
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => void upload(event.target.files)}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading || state.busy}
          title="Attach files (or drag & drop here)"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
        >
          {uploading ? (
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
          ) : (
            <Paperclip className="h-4 w-4" />
          )}
        </button>

        <ComposerPrimitive.Input
          placeholder="Ask anything, drag & drop files, or summarize documents..."
          rows={1}
          submitMode="enter"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              if (state.busy) return
              const form = (e.target as HTMLElement).closest("form")
              if (form) {
                form.requestSubmit()
              } else {
                aui.composer.send()
              }
            }
          }}
          className={cn(
            "max-h-48 min-h-10 flex-1 resize-none bg-transparent py-2 px-1 text-[15px] leading-relaxed",
            "placeholder:text-muted-foreground focus:outline-none"
          )}
        />

        <button
          type="button"
          onClick={() => atlas.setThinking(!state.thinking)}
          disabled={state.busy}
          title={state.thinking ? "Reasoning / Thinking: ON" : "Reasoning / Thinking: OFF"}
          aria-pressed={state.thinking}
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-colors disabled:opacity-40",
            state.thinking
              ? "bg-primary text-primary-foreground shadow-xs"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          <Brain className="h-4 w-4" />
        </button>

        {state.busy ? (
          <button
            type="button"
            onClick={() => void atlas.cancel()}
            title="Stop generation"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground text-background transition-opacity hover:opacity-90 shadow-xs"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : (
          <ComposerPrimitive.Send className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-foreground text-background transition-opacity hover:opacity-90 shadow-xs">
            <ArrowUp className="h-4 w-4 stroke-[2.5]" />
          </ComposerPrimitive.Send>
        )}
      </div>
    </ComposerPrimitive.Root>
  )
}
