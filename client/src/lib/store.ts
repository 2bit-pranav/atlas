/**
 * The client's single source of truth.
 *
 * ## Why it is fast now
 *
 * The old store rebuilt the whole thread on every SSE delta and re-parsed every
 * message's markdown, so a reasoning stream of a few hundred tokens meant a few
 * hundred full-thread renders. Three changes:
 *
 * 1. **Selectors.** `useAtlas(s => s.x)` re-renders a component only when its
 *    own slice changes. The sidebar does not render when a token arrives; a
 *    finished turn does not render when another turn streams.
 * 2. **One update per frame.** SSE events are buffered and folded once per
 *    `requestAnimationFrame`, however many arrived. Text appears at display
 *    rate, not at the rate the network delivers it.
 * 3. **Structural sharing.** Only the live turn's parts get a new identity, so
 *    `React.memo` rows short-circuit everywhere else.
 *
 * ## The rule that matters
 *
 * A run that is not finished is never forgotten: `seq` survives reconnects and
 * the stream resubscribes with `after=seq+1`, so a dropped connection costs a
 * pause, not a lost or repeated sentence.
 */

import { useSyncExternalStore } from "react"

import * as api from "@/lib/api"
import { emptyLive, fold, type LiveTurn } from "@/lib/transcript"
import { ApiError } from "@/lib/types"
import type {
  ChatFile,
  ChatSummary,
  Ref,
  ChatView,
  RunEvent,
  RunRef,
  SettingsView,
  StartedRun,
  TurnStats,
} from "@/lib/types"

export interface Staged extends ChatFile {
  /** Local id while uploading; replaced by the server path when done. */
  key: string
  uploading: boolean
}

export interface AtlasState {
  chats: ChatSummary[]
  chatsLoaded: boolean
  chat: ChatView | null
  /** The run being streamed into `live`, if any. */
  run: RunRef | null
  live: LiveTurn | null
  settings: SettingsView | null
  thinking: boolean
  staged: Staged[]
  /** The chat a staged upload belongs to. Uploads need a chat to live in. */
  stagedChat: string | null
  error: string | null
  connected: boolean
  /** Bumps when something asks the composer to take focus. */
  focusTick: number
  /** The workspace file open in the preview panel, if any. */
  preview: string | null
  /** Bumps when the open file may have changed on disk, so the panel reloads it. */
  previewTick: number
  /** Passages selected in the preview, waiting to go with the next message. */
  refs: Ref[]
  /** A restart from the UI in progress (llama-server and the backend). */
  restarting: boolean
  /** Why the last restart failed; the model is not running until another one works. */
  restartError: string | null
}

type Listener = () => void

class Store {
  state: AtlasState = {
    chats: [],
    chatsLoaded: false,
    chat: null,
    run: null,
    live: null,
    settings: null,
    thinking: false,
    staged: [],
    stagedChat: null,
    error: null,
    connected: true,
    focusTick: 0,
    preview: null,
    previewTick: 0,
    refs: [],
    restarting: false,
    restartError: null,
  }

  private listeners = new Set<Listener>()
  private seq = -1
  private stream: api.EventStream | null = null
  private generation = 0
  private pending: RunEvent[] = []
  private frame = 0

  subscribe = (l: Listener) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }

  set(patch: Partial<AtlasState>) {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((l) => l())
  }

  fail(error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    this.set({ error: message, connected: !(error instanceof ApiError && error.status === 0) })
  }

  clearError = () => this.set({ error: null })

  /**
   * Restart llama-server and the backend with the saved settings: how a new
   * model or another restart setting takes effect. The backend goes away
   * while it happens, so this polls until the restart it asked for reports
   * back (its `at` is newer than the request), then reloads settings.
   */
  async restart(): Promise<boolean> {
    if (this.state.restarting) return false
    const asked = Date.now()
    try {
      await api.restart()
    } catch (error) {
      this.fail(error)
      return false
    }
    this.set({ restarting: true, error: null })
    const deadline = asked + 10 * 60_000
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1000))
      try {
        const status = await api.restartStatus()
        if (status.at && status.at >= asked && status.state !== "restarting") {
          const failed = status.state === "failed" ? status.error ?? "failed" : null
          this.set({ restarting: false, connected: true, restartError: failed, settings: await api.getSettings() })
          return failed === null
        }
      } catch {
        // The backend is down while it restarts; keep waiting.
      }
    }
    this.set({ restarting: false, restartError: "Restart is taking too long. Check the terminal running `atlas start`." })
    return false
  }

  /** Whether the last restart failed, e.g. after reloading the page. */
  async checkRestart() {
    try {
      const status = await api.restartStatus()
      this.set({ restartError: status.state === "failed" ? status.error ?? "failed" : null })
    } catch {
      // Not critical: the Settings page simply shows no restart notice.
    }
  }

  // ---------------------------------------------------------------- boot --

  async init() {
    try {
      const [settings, chats] = await Promise.all([api.getSettings(), api.listChats()])
      this.set({
        settings, chats, chatsLoaded: true, connected: true,
        thinking: Boolean(settings.values["sampling.thinking"]),
      })
    } catch (error) {
      this.set({ chatsLoaded: true })
      this.fail(error)
    }
  }

  async refreshChats() {
    try {
      this.set({ chats: await api.listChats() })
    } catch {
      /* the transcript matters more than a stale sidebar */
    }
  }

  async refreshSettings() {
    try {
      this.set({ settings: await api.getSettings() })
    } catch (error) {
      this.fail(error)
    }
  }

  async saveSettings(patch: Record<string, unknown>): Promise<boolean> {
    try {
      this.set({ settings: await api.putSettings(patch), error: null })
      return true
    } catch (error) {
      this.fail(error)
      return false
    }
  }

  // --------------------------------------------------------------- chats --

  /** Show an empty chat. Nothing is created until the first message. */
  newChat() {
    this.detach()
    this.set({ chat: null, run: null, live: null, error: null, preview: null, refs: [],
               focusTick: this.state.focusTick + 1 })
  }

  async openChat(id: string) {
    if (this.state.chat?.id === id) return
    this.detach()
    try {
      const chat = await api.getChat(id)
      this.set({ chat, run: chat.active_run, live: null, error: null, preview: null, refs: [],
                 staged: this.state.stagedChat === id ? this.state.staged : [],
                 focusTick: this.state.focusTick + 1 })
      if (chat.active_run) this.attach(chat.active_run)
    } catch (error) {
      this.fail(error)
    }
  }

  async renameChat(id: string, title: string) {
    try {
      const updated = await api.renameChat(id, title)
      this.set({
        chats: this.state.chats.map((c) => (c.id === id ? { ...c, title: updated.title } : c)),
        chat: this.state.chat?.id === id ? { ...this.state.chat, title: updated.title } : this.state.chat,
      })
    } catch (error) {
      this.fail(error)
    }
  }

  async deleteChat(id: string) {
    try {
      await api.deleteChat(id)
      this.set({ chats: this.state.chats.filter((c) => c.id !== id) })
      if (this.state.chat?.id === id) this.newChat()
    } catch (error) {
      this.fail(error)
    }
  }

  async deleteAllChats() {
    for (const chat of [...this.state.chats]) await this.deleteChat(chat.id)
  }

  private async ensureChat(): Promise<string> {
    if (this.state.chat) return this.state.chat.id
    if (this.state.stagedChat) return this.state.stagedChat
    const created = await api.createChat()
    this.set({ chats: [created, ...this.state.chats], stagedChat: created.id })
    return created.id
  }

  // --------------------------------------------------------- attachments --

  async attach_files(files: File[]) {
    if (!files.length) return
    let chatId: string
    try {
      chatId = await this.ensureChat()
    } catch (error) {
      return this.fail(error)
    }
    const placeholders: Staged[] = files.map((f) => ({
      key: crypto.randomUUID(), name: f.name, path: "", size: f.size,
      type: f.type || "application/octet-stream", uploading: true,
    }))
    this.set({ staged: [...this.state.staged, ...placeholders], stagedChat: chatId })
    await Promise.all(files.map(async (file, i) => {
      const key = placeholders[i].key
      try {
        const saved = await api.uploadFile(chatId, file)
        this.set({ staged: this.state.staged.map((s) => (s.key === key ? { ...saved, key, uploading: false } : s)) })
      } catch (error) {
        this.set({ staged: this.state.staged.filter((s) => s.key !== key) })
        this.fail(error)
      }
    }))
  }

  /**
   * Take a file off the message being written. It was already uploaded, so
   * it is deleted too: otherwise it lingers in the workspace and in the @ menu
   * as if it had been sent. (The backend keeps any file a sent message used.)
   */
  unstage(key: string) {
    const file = this.state.staged.find((s) => s.key === key)
    this.set({ staged: this.state.staged.filter((s) => s.key !== key) })
    const chatId = this.state.chat?.id ?? this.state.stagedChat
    if (file && !file.uploading && file.path && chatId)
      void api.deleteUpload(chatId, file.name).catch(() => undefined)
  }

  // -------------------------------------------------------------- preview --

  openPreview(path: string) {
    this.set({ preview: path, previewTick: this.state.previewTick + 1 })
  }

  closePreview() {
    this.set({ preview: null })
  }

  addRef(ref: Ref) {
    if (this.state.refs.some((r) => r.file === ref.file && r.quote === ref.quote)) return
    this.set({ refs: [...this.state.refs, ref], focusTick: this.state.focusTick + 1 })
  }

  removeRef(index: number) {
    this.set({ refs: this.state.refs.filter((_, i) => i !== index) })
  }

  setThinking(thinking: boolean) {
    this.set({ thinking })
  }

  // ------------------------------------------------------------- turning --

  get busy() {
    return this.state.run !== null
  }

  async send(text: string): Promise<boolean> {
    if (this.busy || this.state.staged.some((s) => s.uploading)) return false
    const files = this.state.staged.map(({ key: _k, uploading: _u, ...f }) => f)
    const refs = this.state.refs
    if (!text.trim() && !files.length && !refs.length) return false
    try {
      const chatId = await this.ensureChat()
      const started = await api.send(chatId, { text, files, refs, thinking: this.state.thinking })
      this.set({ staged: [], stagedChat: null, refs: [] })
      this.begin(started)
      void this.refreshChats()
      return true
    } catch (error) {
      this.fail(error)
      return false
    }
  }

  async retry(turnId: string) {
    if (this.busy) return
    try {
      this.begin(await api.retry(turnId, this.state.thinking))
    } catch (error) {
      this.fail(error)
    }
  }

  async edit(turnId: string, text: string, files?: ChatFile[]): Promise<boolean> {
    if (this.busy) return false
    try {
      this.begin(await api.edit(turnId, { text, files, thinking: this.state.thinking }))
      return true
    } catch (error) {
      this.fail(error)
      return false
    }
  }

  /**
   * `<` / `>`. Optimistic: the arrows update at once from the version list the
   * client already has, then the server's path replaces it. Waiting for the
   * round trip before moving the counter is what read as lag.
   */
  async selectVersion(turnId: string, delta: number) {
    const chat = this.state.chat
    if (this.busy || !chat) return
    const index = chat.turns.findIndex((t) => t.id === turnId)
    const turn = chat.turns[index]
    if (!turn) return
    const next = Math.max(0, Math.min(turn.version + delta, turn.versions.length - 1))
    if (next === turn.version) return
    this.set({ chat: { ...chat, turns: chat.turns.map((t, i) => (i === index ? { ...t, version: next } : t)) } })
    try {
      this.set({ chat: await api.select(turnId, delta) })
    } catch (error) {
      this.set({ chat })
      this.fail(error)
    }
  }

  async answerApproval(approvalId: string, allow: boolean) {
    const run = this.state.run
    if (!run) return
    try {
      await api.answerApproval(run.id, approvalId, allow)
    } catch (error) {
      this.fail(error)
    }
  }

  async cancel() {
    const run = this.state.run
    if (!run) return
    try {
      await api.cancel(run.id)
    } catch (error) {
      this.fail(error)
    }
  }

  // ----------------------------------------------------------- streaming --

  private begin({ run, chat }: StartedRun) {
    this.detach()
    const size = Number(this.state.settings?.values["model.context_size"] ?? 0)
    this.set({ chat, run, live: emptyLive(size), error: null })
    this.attach(run)
  }

  private attach(run: RunRef) {
    const generation = ++this.generation
    this.seq = -1
    if (!this.state.live) {
      const size = Number(this.state.settings?.values["model.context_size"] ?? 0)
      this.set({ live: emptyLive(size) })
    }
    void this.follow(run, generation)
  }

  private detach() {
    this.generation += 1
    this.stream?.close()
    this.stream = null
    this.pending = []
    if (this.frame) cancelAnimationFrame(this.frame)
    this.frame = 0
  }

  private async follow(run: RunRef, generation: number) {
    for (let attempt = 0; attempt < 10; attempt++) {
      if (generation !== this.generation) return
      let terminal = false
      try {
        const stream = api.streamRun(run.id, this.seq + 1, (event) => {
          if (generation !== this.generation || event.seq <= this.seq) return
          this.seq = event.seq
          this.pending.push(event)
          if (event.type === "done" || event.type === "error") terminal = true
          if (!this.frame) this.frame = requestAnimationFrame(() => this.flush(generation))
        })
        this.stream = stream
        await stream.done
        if (terminal || generation !== this.generation) return
      } catch {
        if (generation !== this.generation) return
      }
      // Ended without a terminal event: a dropped connection, or a run the
      // server already finished and swept.
      try {
        const status = await api.getRun(run.id)
        if (status.status !== "running") return void this.finish(run, status.error)
      } catch {
        return void this.finish(run, null)
      }
      await new Promise((r) => setTimeout(r, 300 * (attempt + 1)))
    }
  }

  private flush(generation: number) {
    this.frame = 0
    if (generation !== this.generation || !this.state.live) return
    const events = this.pending
    this.pending = []
    const live = this.state.live
    let finished: { error: string | null } | null = null
    for (const event of events) {
      if (event.type === "done") finished = { error: null }
      else if (event.type === "error") finished = { error: event.message }
      else fold(live, event)
    }
    this.set({ live: { ...live, parts: [...live.parts] } })
    if (finished && this.state.run) void this.finish(this.state.run, finished.error)
  }

  private async finish(run: RunRef, error: string | null) {
    const chatId = run.chat_id
    try {
      const chat = await api.getChat(chatId)
      // Replace the live view and the stored transcript in one update, so the
      // answer never blinks out between the two.
      if (this.state.chat?.id === chatId) this.set({ chat })
      const touched = chat.turns.at(-1)?.stats?.files ?? []
      if (this.state.preview && touched.some((f) => f.name === this.state.preview))
        this.set({ previewTick: this.state.previewTick + 1 })
    } catch {
      /* keep what was streamed */
    }
    this.set({ run: null, live: null, error: error ?? this.state.error })
    void this.refreshChats()
  }

  // -------------------------------------------------------------- export --

  async exportChats(ids: string[]): Promise<unknown[]> {
    return Promise.all(ids.map((id) => api.exportChat(id)))
  }

  async importChats(data: unknown): Promise<number> {
    const items = Array.isArray(data) ? data : [data]
    let count = 0
    for (const item of items) {
      await api.importChat(item)
      count += 1
    }
    await this.refreshChats()
    return count
  }
}

export const atlas = new Store()

/** Subscribe to one slice. The component re-renders only when it changes. */
export function useAtlas<T>(selector: (s: AtlasState) => T): T {
  return useSyncExternalStore(atlas.subscribe, () => selector(atlas.state))
}

/** The stats to show in the composer: the live run's, or the last turn's. */
export function currentStats(s: AtlasState): TurnStats | null {
  if (s.live) return s.live.stats
  const turns = s.chat?.turns
  return turns?.length ? turns[turns.length - 1].stats : null
}
