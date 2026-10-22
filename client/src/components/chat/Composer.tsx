/**
 * The message box, after llama.cpp's `ChatForm`.
 *
 * One component for both jobs: the composer at the bottom of the chat, and the
 * inline editor that replaces a user message in place. In edit mode it keeps
 * its own text and files; in main mode the staged files live in the store,
 * because uploads have to outlive a re-render and belong to a chat.
 */

import { memo, useEffect, useLayoutEffect, useRef, useState } from "react"
import * as Dropdown from "@radix-ui/react-dropdown-menu"
import { ArrowUp, Check, File as FileIcon, Lightbulb, LightbulbOff, Loader2, Mic, Plus, Square, X } from "lucide-react"

import * as api from "@/lib/api"
import { atlas, useAtlas } from "@/lib/store"
import { usePrefs } from "@/lib/prefs"
import type { ChatFile } from "@/lib/types"
import { cn } from "@/lib/utils"
import { Tip } from "@/components/ui/tip"
import { ContextGauge } from "@/components/chat/ContextGauge"
import { filterMentions, MentionMenu, useMentionables, type Mention } from "@/components/chat/MentionMenu"
import { Recorder } from "@/lib/audio"

/** Pasting more than this many characters attaches the text as a file instead. */
const PASTE_AS_FILE = 2500

const INPUT_CLASSES =
  "bg-muted/60 dark:bg-muted/75 border border-border/30 focus-within:border-border dark:border-border/20 dark:focus-within:border-border shadow-sm outline-none text-foreground"

interface EditProps {
  initialText: string
  initialFiles: ChatFile[]
  onSubmit: (text: string, files: ChatFile[]) => Promise<boolean>
  onCancel: () => void
}

export const Composer = memo(function Composer({ edit }: { edit?: EditProps }) {
  const prefs = usePrefs()
  const busy = useAtlas((s) => s.run !== null)
  const staged = useAtlas((s) => s.staged)
  const thinking = useAtlas((s) => s.thinking)
  const focusTick = useAtlas((s) => s.focusTick)
  const supportsThinking = useAtlas((s) => s.settings?.values["model.supports_thinking"] !== false)
  const modelName = useAtlas((s) => String(s.settings?.values["model.name"] ?? ""))
  const hearsAudio = useAtlas((s) => Boolean(s.settings?.modalities?.audio))
  const chatId = useAtlas((s) => s.chat?.id ?? s.stagedChat)

  const [text, setText] = useState(edit?.initialText ?? "")
  const [editFiles, setEditFiles] = useState<ChatFile[]>(edit?.initialFiles ?? [])
  const area = useRef<HTMLTextAreaElement>(null)
  const picker = useRef<HTMLInputElement>(null)

  // @ mentions: the "@query" being typed at the caret, if any.
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null)
  const [mentionIndex, setMentionIndex] = useState(0)
  const mentionables = useMentionables(chatId, mention !== null)
  const matches = mention ? filterMentions(mentionables, mention.query) : []

  const trackMention = (value: string, caret: number) => {
    const m = /(^|\s)@([\w.-]*)$/.exec(value.slice(0, caret))
    setMention(m ? { start: caret - m[2].length - 1, query: m[2] } : null)
    setMentionIndex(0)
  }

  const pickMention = (m: Mention) => {
    const el = area.current
    if (!mention || !el) return
    const caret = el.selectionStart
    // Inserted as text. A name with spaces or other characters is quoted, so
    // the backend can find where it ends.
    const insert = /^[\w.-]+$/.test(m.name) ? `@${m.name} ` : `@"${m.name}" `
    const next = text.slice(0, mention.start) + insert + text.slice(caret)
    setText(next)
    setMention(null)
    requestAnimationFrame(() => {
      el.focus()
      const at = mention.start + insert.length
      el.setSelectionRange(at, at)
    })
  }

  // Voice: attach the recording itself; the model hears audio, no transcription.
  const recorder = useRef<Recorder | null>(null)
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!recording) return
    const timer = setInterval(() => setElapsed(Date.now() - (recorder.current?.startedAt ?? Date.now())), 250)
    return () => clearInterval(timer)
  }, [recording])
  const startRecording = async () => {
    try {
      recorder.current = new Recorder()
      await recorder.current.start()
      setElapsed(0)
      setRecording(true)
    } catch (error) {
      atlas.fail(new Error(`Microphone unavailable: ${error instanceof Error ? error.message : error}`))
    }
  }
  const stopRecording = async (keep: boolean) => {
    setRecording(false)
    const file = await recorder.current?.stop(keep)
    recorder.current = null
    if (file) await addFiles([file])
  }

  const files = edit ? editFiles.map((f) => ({ ...f, key: f.path, uploading: false })) : staged
  const uploading = files.some((f) => f.uploading)
  const canSend = !uploading && (text.trim().length > 0 || files.length > 0) &&
    (!busy || Boolean(edit))

  // Grow with the text, up to llama.cpp's max-message-height.
  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = "0px"
    el.style.height = `${Math.min(el.scrollHeight, window.innerHeight * 0.4)}px`
  }, [text])

  useEffect(() => {
    if (!edit) area.current?.focus()
  }, [focusTick, edit])

  useEffect(() => {
    if (edit) {
      const el = area.current
      el?.focus()
      el?.setSelectionRange(el.value.length, el.value.length)
    }
  }, [edit])

  const addFiles = async (list: File[]) => {
    if (!list.length) return
    if (!edit) return atlas.attach_files(list)
    // Editing: upload into the same chat, keep the result local to the editor.
    const chatId = atlas.state.chat?.id
    if (!chatId) return
    for (const file of list) {
      try {
        const saved = await api.uploadFile(chatId, file)
        setEditFiles((f) => [...f, saved])
      } catch (error) {
        atlas.fail(error)
      }
    }
  }

  const submit = async () => {
    if (!canSend) return
    if (edit) {
      if (await edit.onSubmit(text, editFiles)) setText("")
      return
    }
    const sent = text
    setText("")
    if (!(await atlas.send(sent))) setText(sent)
  }

  return (
    <form
      className="relative mx-auto grid w-full max-w-3xl"
      onSubmit={(e) => { e.preventDefault(); void submit() }}
    >
      {mention && (
        <MentionMenu items={matches} query={mention.query} index={mentionIndex}
                     onPick={pickMention} onHover={setMentionIndex} />
      )}
      <div className={cn(INPUT_CLASSES, "overflow-hidden rounded-4xl backdrop-blur-md md:rounded-3xl")}>
        {files.length > 0 && (
          <div className="flex gap-2 overflow-x-auto px-3 pt-3">
            {files.map((f) => (
              <FileChip key={f.key} file={f} uploading={f.uploading}
                        onRemove={() => edit ? setEditFiles((x) => x.filter((y) => y.path !== f.path)) : atlas.unstage(f.key)} />
            ))}
          </div>
        )}
        <div className="relative min-h-12 py-2 md:py-3">
          {recording && (
            <div className="flex items-center gap-3 px-5 py-1.5 text-sm">
              <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" />
              <span className="font-mono tabular-nums">
                {Math.floor(elapsed / 60000)}:{String(Math.floor(elapsed / 1000) % 60).padStart(2, "0")}
              </span>
              <span className="text-muted-foreground">Recording. Stop to attach it.</span>
            </div>
          )}
          <div className={cn("px-5 py-1.5", recording && "hidden")}>
            <textarea
              ref={area}
              rows={1}
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                trackMention(e.target.value, e.target.selectionStart)
              }}
              onClick={(e) => trackMention(e.currentTarget.value, e.currentTarget.selectionStart)}
              onBlur={() => setMention(null)}
              placeholder={edit ? "Edit your message..." : "Type a message, or @ to point at a file, skill or tool..."}
              className="block min-h-6 w-full resize-none border-0 bg-transparent p-0 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
              onKeyDown={(e) => {
                if (mention) {
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault()
                    const n = Math.max(1, matches.length)
                    setMentionIndex((i) => (i + (e.key === "ArrowDown" ? 1 : n - 1)) % n)
                    return
                  }
                  if ((e.key === "Enter" || e.key === "Tab") && matches[mentionIndex]) {
                    e.preventDefault()
                    pickMention(matches[mentionIndex])
                    return
                  }
                  if (e.key === "Escape") {
                    e.preventDefault()
                    setMention(null)
                    return
                  }
                }
                if (e.key === "Escape" && edit) return edit.onCancel()
                if (e.key !== "Enter" || e.nativeEvent.isComposing) return
                const mod = e.ctrlKey || e.metaKey
                const send = prefs.sendOnEnter ? !e.shiftKey : mod
                if (send) {
                  e.preventDefault()
                  void submit()
                }
              }}
              onPaste={(e) => {
                const pasted = Array.from(e.clipboardData.files)
                if (pasted.length) {
                  e.preventDefault()
                  void addFiles(pasted)
                  return
                }
                const clip = e.clipboardData.getData("text")
                if (clip.length > PASTE_AS_FILE) {
                  e.preventDefault()
                  void addFiles([new File([clip], `pasted-${Date.now()}.txt`, { type: "text/plain" })])
                }
              }}
            />
          </div>

          <div className="flex items-center gap-3 px-3 pt-1">
            <Dropdown.Root>
              <Tip label="Add files">
                <Dropdown.Trigger asChild>
                  <button type="button" className="flex h-8 w-8 items-center justify-center rounded-full bg-background shadow-sm hover:bg-accent dark:bg-muted-foreground/15">
                    <Plus className="h-4 w-4" />
                  </button>
                </Dropdown.Trigger>
              </Tip>
              <Dropdown.Portal>
                <Dropdown.Content side="top" align="start" sideOffset={6}
                                  className="z-50 w-52 rounded-lg border bg-popover p-1 text-sm shadow-md">
                  <Dropdown.Item onSelect={() => picker.current?.click()}
                                 className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 outline-none data-[highlighted]:bg-accent">
                    <FileIcon className="h-4 w-4" />Add files
                  </Dropdown.Item>
                </Dropdown.Content>
              </Dropdown.Portal>
            </Dropdown.Root>
            <input ref={picker} type="file" multiple hidden onChange={(e) => {
              const list = Array.from(e.target.files ?? [])
              e.target.value = ""
              void addFiles(list)
            }} />

            <div className="ml-auto flex items-center gap-1.5">
              {!edit && prefs.showContextMeter && <ContextGauge />}
              {supportsThinking && (
                <Tip label={thinking ? "Thinking on" : "Thinking off"}>
                  <button type="button" onClick={() => atlas.setThinking(!thinking)}
                          aria-pressed={thinking}
                          className={cn("flex h-8 items-center gap-1 rounded-full px-2 text-xs hover:bg-muted-foreground/10",
                                        thinking ? "text-foreground" : "text-muted-foreground")}>
                    {thinking ? <Lightbulb className="h-4 w-4" /> : <LightbulbOff className="h-4 w-4" />}
                    {thinking && <span className="hidden sm:inline">Think</span>}
                  </button>
                </Tip>
              )}
              {!edit && modelName && (
                <span className="hidden max-w-40 truncate rounded-sm bg-background px-1.5 py-1 text-xs shadow-sm dark:bg-muted-foreground/15 sm:inline" title={modelName}>
                  {modelName}
                </span>
              )}
            </div>

            {recording ? (
              <>
                <Tip label="Discard recording">
                  <button type="button" onClick={() => void stopRecording(false)}
                          className="flex h-9 w-9 items-center justify-center rounded-full hover:bg-muted-foreground/10 md:h-8 md:w-8">
                    <X className="h-4 w-4" />
                  </button>
                </Tip>
                <Tip label="Stop and attach">
                  <button type="button" onClick={() => void stopRecording(true)}
                          className="flex h-9 w-9 items-center justify-center rounded-full bg-red-500 text-white md:h-8 md:w-8">
                    <Check className="h-4 w-4" />
                  </button>
                </Tip>
              </>
            ) : null}
            {!recording && hearsAudio && !text.trim() && typeof MediaRecorder !== "undefined" && (
              <Tip label="Record audio">
                <button type="button" onClick={() => void startRecording()} aria-label="Record audio"
                        className="flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted-foreground/10 hover:text-foreground md:h-8 md:w-8">
                  <Mic className="h-4 w-4" />
                </button>
              </Tip>
            )}
            {recording ? null : busy && !edit && !text.trim() ? (
              <Tip label="Stop">
                <button type="button" onClick={() => void atlas.cancel()}
                        className="group flex h-9 w-9 items-center justify-center rounded-full border border-muted bg-muted/30 shadow-sm hover:bg-muted md:h-8 md:w-8 dark:bg-muted-foreground/15">
                  <Square className="h-3 w-3 fill-muted-foreground text-muted-foreground group-hover:fill-destructive group-hover:text-destructive" />
                </button>
              </Tip>
            ) : (
              <button type="submit" disabled={!canSend} aria-label="Send"
                      className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity disabled:opacity-40 md:h-8 md:w-8">
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
              </button>
            )}
          </div>
        </div>
      </div>
    </form>
  )
})

function FileChip({ file, uploading, onRemove }: { file: ChatFile; uploading: boolean; onRemove: () => void }) {
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
  return (
    <div className="group relative flex shrink-0 items-center gap-3 rounded-lg border bg-muted p-2.5 pr-7">
      <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">
        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : ext}
      </span>
      <span className="min-w-0">
        <span className="block max-w-32 truncate text-sm font-medium">{file.name}</span>
        <span className="block text-xs text-muted-foreground">{formatBytes(file.size)}</span>
      </span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${file.name}`}
              className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground opacity-100 hover:bg-background hover:text-foreground md:opacity-0 md:group-hover:opacity-100">
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

