/**
 * The single source of truth for what the UI shows.
 *
 * The backend owns the messages; this owns the *projection* of them. Every
 * render reads from here, and every change arrives here first. Nothing else in
 * the client keeps a parallel copy, because two copies of a streaming answer
 * drift apart within a second and there is no way to tell which one is right.
 *
 * ## Why this is a hand-rolled store and not `useState`
 *
 * SSE events arrive faster than React renders, and the sequence numbers that
 * make resumption work have to be remembered somewhere outside React's batching
 * or a burst of deltas can commit out of order. `useSyncExternalStore` gives us
 * a snapshot identity React can compare, and the cursor lives on the instance.
 *
 * ## The rule that matters
 *
 * A run that is not finished is not allowed to be forgotten. The store keeps
 * `runId` and `seq` across reconnects and resubscribes with `after=seq`, so a
 * dropped connection resumes exactly where it stopped -- no gap, no duplicate
 * word, no duplicated turn.
 */

import { useCallback, useSyncExternalStore } from "react"

import * as api from "@/services/atlasApi"
import type {
  ChatFile,
  ChatListItem,
  RunEvent,
  SettingsView,
  TurnView,
} from "@/types/api"

// --------------------------------------------------------------- messages --

export type MessagePart =
  | { kind: "text"; text: string }
  | { kind: "reasoning"; text: string }
  | {
      kind: "tool"
      /** The backend's `toolUseId`. Stable across events, so it is the React key. */
      id: string
      name: string
      args: unknown
      status: "running" | "success" | "error"
      text: string
    }

export interface AtlasMessage {
  id: string
  role: "user" | "assistant"
  turnId: string
  files: ChatFile[]
  parts: MessagePart[]
  /** While true the answer is still growing. Drives the typing indicator. */
  running: boolean
  status: TurnView["status"]
  createdAt: number
}

// ------------------------------------------------------------------ state --

export interface AtlasState {
  chats: ChatListItem[]
  chatId: string | null
  turns: TurnView[]
  messages: AtlasMessage[]
  settings: SettingsView | null
  /** Non-null when the backend is unreachable or rejected something. */
  error: string | null
  connected: boolean
  runId: string | null
  busy: boolean
  /** Per-send override for the model's reasoning mode. */
  thinking: boolean
  /**
   * Files uploaded but not yet sent.
   *
   * Owned here, and only here. It used to be a module-level list in
   * `atlasRuntime` that the Composer wrote and `onNew` read -- two owners with
   * no ordering between them. The Composer's send button cleared it on click,
   * which runs *before* assistant-ui calls `onNew`, so every attachment was
   * silently dropped and the model was asked a question about a file it had
   * never heard of. One owner removes the race rather than papering over it.
   */
  staged: ChatFile[]
  usage: UsageReport | null
  draftText: string | null
  draftTimestamp: number
}

export interface UsageReport {
  input: number
  output: number
  total: number
  /** True when the model reported nothing at all. */
  unreported: boolean
}

// ------------------------------------------------------------------ store --

class AtlasStore {
  private state: AtlasState = {
    chats: [],
    chatId: null,
    turns: [],
    messages: [],
    settings: null,
    error: null,
    connected: false,
    runId: null,
    busy: false,
    thinking: false,
    usage: null,
    staged: [],
    draftText: null,
    draftTimestamp: 0,
  }

  private listeners = new Set<() => void>()

  /** Resume cursor. Survives reconnects and is only ever raised. */
  private seq = -1
  private stream: api.EventStream | null = null
  /** Invalidates a reader when the user switches chats or starts another run. */
  private streamGeneration = 0
  /** The message deltas are currently being appended to. */
  private streamingId: string | null = null

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot = (): AtlasState => this.state

  private set(patch: Partial<AtlasState>) {
    this.state = { ...this.state, ...patch }
    this.listeners.forEach((listener) => listener())
  }

  // ------------------------------------------------------------- helpers --

  /**
   * Immutably replace one message. Every event routes through here, so there
   * is exactly one place that knows how a message is rebuilt -- and it is a
   * pure function of (message, event).
   */
  private update(id: string, fn: (message: AtlasMessage) => AtlasMessage) {
    this.set({
      messages: this.state.messages.map((m) => (m.id === id ? fn(m) : m)),
    })
  }

  private appendTo(id: string, part: MessagePart) {
    this.update(id, (m) => ({ ...m, parts: [...m.parts, part] }))
  }

  private lastAssistantId(): string | null {
    const last = this.state.messages[this.state.messages.length - 1]
    return last && last.role === "assistant" ? last.id : null
  }

  // -------------------------------------------------------------- loading --

  /** Read settings and chats together; the modal needs both on first paint. */
  async init() {
    try {
      const [settings, chats] = await Promise.all([
        api.getSettings(),
        api.listChats(),
      ])
      this.set({
        settings,
        chats,
        thinking: Boolean(settings.values["sampling.thinking"]),
        connected: true,
        error: null,
      })
    } catch (error) {
      this.report(error)
    }
  }

  private report(error: unknown) {
    const message =
      error instanceof Error ? error.message : "something went wrong"
    this.set({ error: message, connected: false })
  }

  async refreshSettings() {
    try {
      this.set({ settings: await api.getSettings() })
    } catch (error) {
      this.report(error)
    }
  }

  /**
   * Save settings. Returns false on failure so the modal can keep the field
   * open and show why, rather than optimistically closing on a rejected write.
   */
  async saveSettings(patch: Record<string, unknown>): Promise<boolean> {
    try {
      this.set({ settings: await api.putSettings(patch), error: null })
      return true
    } catch (error) {
      this.report(error)
      return false
    }
  }

  // ---------------------------------------------------------------- chats --

  async newChat(title = "") {
    try {
      const chat = await api.createChat(title)
      this.seq = -1
      this.set({
        chatId: chat.id,
        turns: [],
        messages: [],
        runId: null,
        chats: [{ ...chat, created_at: Date.now(), updated_at: Date.now() }, ...this.state.chats],
        error: null,
      })
      // Listing is not on the critical path for the first prompt. Waiting for
      // it kept the empty screen visible even though the chat already existed.
      void api.listChats().then((chats) => this.set({ chats })).catch(() => undefined)
    } catch (error) {
      this.report(error)
    }
  }

  /**
   * Open a chat. Turns are replayed from the backend's stored messages rather
   * than from a local cache, because a turn's *answer* is a Strands snapshot
   * and the backend is the only thing that can read one.
   */
  async openChat(chatId: string) {
    this.stop()
    try {
      const chat = await api.getChat(chatId)
      const messages: AtlasMessage[] = []
      for (const turn of chat.turns) {
        messages.push(userMessage(turn))
        messages.push(await assistantMessage(chatId, turn))
      }
      this.seq = -1
      this.set({
        chatId,
        turns: chat.turns,
        messages,
        runId: chat.active_run,
        busy: Boolean(chat.active_run),
        error: null,
      })
      const activeTurn = chat.turns.at(-1)?.id
      if (chat.active_run && activeTurn) {
        void this.resume(chat.active_run, activeTurn, chatId)
      }
    } catch (error) {
      this.report(error)
    }
  }

  // ------------------------------------------------------------- attachments --

  stageFiles(files: ChatFile[]) {
    this.set({ staged: [...this.state.staged, ...files] })
  }

  unstageFile(path: string) {
    this.set({ staged: this.state.staged.filter((f) => f.path !== path) })
  }

  populateComposer(text: string, files?: ChatFile[]) {
    this.set({
      draftText: text,
      draftTimestamp: Date.now(),
      staged: files ? [...files] : [],
    })
  }

  clearDraft() {
    this.set({ draftText: null })
  }

  async deleteChat(chatId: string) {
    try {
      await api.deleteChat(chatId)
      const chats = await api.listChats()
      if (this.state.chatId === chatId) {
        this.set({ chatId: null, turns: [], messages: [], runId: null, chats })
      } else {
        this.set({ chats })
      }
    } catch (error) {
      this.report(error)
    }
  }

  // ------------------------------------------------------------- sending --

  /** Creates a chat on demand, so the first message is not a special case. */
  private async ensureChat(): Promise<string | null> {
    if (this.state.chatId) return this.state.chatId
    await this.newChat()
    return this.state.chatId
  }

  async send(text: string, files?: ChatFile[], thinking?: boolean) {
    if (this.state.busy) return
    const chatId = await this.ensureChat()
    if (!chatId) return
    // Whatever is staged goes with this message, and only with this one.
    const attachments = files ?? this.state.staged
    const localId = `pending:${crypto.randomUUID()}`
    const optimistic = optimisticTurn(localId, text, attachments)
    try {
      // Move out of the welcome screen before waiting for POST /messages.
      this.set({
        busy: true,
        error: null,
        staged: [],
        turns: [...this.state.turns, optimistic],
        messages: [...this.state.messages, userMessage(optimistic)],
      })
      const { run_id, turn_id } = await api.sendMessage(chatId, {
        text,
        files: attachments,
        thinking: thinking ?? this.state.thinking,
      })
      const turn = optimisticTurn(turn_id, text, attachments)
      this.set({
        turns: this.state.turns.map((item) => item.id === localId ? turn : item),
        messages: this.state.messages.map((item) =>
          item.id === `user:${localId}` ? userMessage(turn) : item,
        ),
      })
      await this.follow(run_id, turn_id)
    } catch (error) {
      this.report(error)
      // The first-send transition is optimistic so it is immediate. If the
      // POST is rejected, remove only that local placeholder; leaving it made
      // a failed send look like a turn that the backend could later retry.
      this.set({
        busy: false,
        turns: this.state.turns.filter((item) => item.id !== localId),
        messages: this.state.messages.filter(
          (item) => item.id !== `user:${localId}`,
        ),
      })
    }
  }

  async retry(turnId: string) {
    if (this.state.busy) return
    try {
      this.set({ busy: true, error: null })
      const { run_id, turn_id } = await api.retryTurn(turnId)
      await this.follow(run_id, turn_id)
    } catch (error) {
      this.report(error)
      this.set({ busy: false })
    }
  }

  /**
   * Editing a turn mints a *sibling*, not a child. The turns below it stay on
   * disk and stay selectable -- editing turn 3 of 5 leaves 4 and 5 intact, they
   * just fall off the visible path. The backend owns that rule; this only has to
   * not contradict it.
   */
  async edit(turnId: string, text: string) {
    if (this.state.busy) return
    try {
      this.set({ busy: true, error: null })
      const { run_id, turn_id } = await api.editTurn(turnId, text)
      await this.follow(run_id, turn_id)
    } catch (error) {
      this.report(error)
      this.set({ busy: false })
    }
  }

  /** `<` and `>` move among a turn's versions. */
  async selectVersion(turnId: string, delta: number) {
    try {
      const result = await api.selectTurn(turnId, delta)
      await this.refreshChat()
      this.set({ error: null })
      void result
    } catch (error) {
      this.report(error)
    }
  }

  async cancel() {
    if (!this.state.runId) return
    try {
      await api.cancelRun(this.state.runId)
    } catch (error) {
      this.report(error)
    }
  }

  setThinking(thinking: boolean) {
    this.set({ thinking })
  }

  // ------------------------------------------------------------ streaming --

  /**
   * Re-read the path after the backend changed it.
   *
   * Only the *last* turn's messages are fetched. Every turn is a snapshot, and
   * reading one replays it through a throwaway agent on the server, so
   * re-reading a fifty-turn transcript on every single reply would cost fifty
   * replays to redraw nine rows that had not changed. Earlier turns are already
   * correct in the projection and are carried over as they are.
   */
  private async refreshChat() {
    const chatId = this.state.chatId
    if (!chatId) return
    const chat = await api.getChat(chatId)

    const messages: AtlasMessage[] = []
    const lastIndex = chat.turns.length - 1

    for (const [index, turn] of chat.turns.entries()) {
      messages.push(userMessage(turn))
      const existing = this.state.messages.find(
        (m) => m.id === `assistant:${turn.id}`,
      )
      if (existing && existing.parts.length > 0) {
        messages.push({
          ...existing,
          files: turn.files,
          status: turn.status,
          running: turn.status === "running",
        })
        continue
      }
      messages.push(await assistantMessage(chatId, turn))
    }

    this.set({ turns: chat.turns, messages })
  }

  /**
   * Attach to a run. Both entry points that create runs end here, so there is
   * one subscription path and one place that decides a run has finished.
   */
  private async follow(runId: string, turnId: string) {
    this.stop()
    const generation = ++this.streamGeneration
    this.seq = -1
    this.streamingId = `assistant:${turnId}`
    this.set({ runId, busy: true })

    // Create the assistant message immediately so the typing indicator has
    // somewhere to live before the first delta arrives.
    const placeholder: AtlasMessage = {
      id: this.streamingId,
      role: "assistant",
      turnId,
      files: [],
      parts: [],
      running: true,
      status: "running",
      createdAt: Date.now(),
    }
    this.set({
      messages: [...this.state.messages, placeholder],
      turns: this.state.turns.map((t) =>
        t.id === turnId ? { ...t, status: "running" } : t,
      ),
    })

    await this.followRun(runId, generation)
  }

  /** Rejoin a server-owned run after opening or reloading a chat. */
  private async resume(runId: string, turnId: string, chatId: string) {
    if (this.state.chatId !== chatId) return
    this.stop()
    const generation = ++this.streamGeneration
    this.seq = -1
    this.streamingId = `assistant:${turnId}`
    this.set({ runId, busy: true })
    await this.followRun(runId, generation)
  }

  /**
   * Subscribe and keep subscribing until a terminal event arrives.
   *
   * The retry loop is the whole point. `seq` is raised on every event, so a
   * reconnect asks for everything after the last one handled -- which is why a
   * dropped connection costs a pause, not a lost or repeated sentence.
   */
  private async followRun(runId: string, generation: number) {
    const MAX_ATTEMPTS = 8

    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      if (generation !== this.streamGeneration) return
      let terminal = false
      try {
        const stream = api.streamRun(runId, this.seq + 1, (event) => {
          if (generation !== this.streamGeneration) return
          // Belt and braces. `after` is an inclusive start index, so `seq + 1`
          // is the correct resume point; this guard means a server that ever
          // changes that semantic degrades to one ignored frame instead of a
          // duplicated sentence.
          if (event.seq <= this.seq) return
          this.seq = event.seq
          terminal = this.apply(event)
        })
        this.stream = stream
        await stream.done
        if (generation !== this.streamGeneration) return
        if (terminal) return
      } catch (error) {
        if (generation !== this.streamGeneration) return
        if (attempt === MAX_ATTEMPTS - 1) {
          this.report(error)
          this.set({ busy: false, runId: null })
          return
        }
      }

      // The stream ended without `done`. If the run is already finished the
      // server has nothing more to say and there is nothing to wait for;
      // otherwise this was a dropped connection, so resubscribe from `seq`.
      try {
        const run = await api.getRun(runId)
        if (generation !== this.streamGeneration) return
        if (run.status === "completed" || run.status === "failed") {
          await this.finish(run.status, run.error)
          return
        }
      } catch {
        /* the backend may be restarting; fall through and retry */
      }
      await new Promise((resolve) => setTimeout(resolve, 400 * (attempt + 1)))
    }
  }

  /**
   * Fold one event into the projection. Returns true for the two terminal
   * events, which is how the subscription loop knows to stop.
   */
  private apply(event: RunEvent): boolean {
    const id = this.streamingId

    switch (event.type) {
      case "run_started": {
        // The placeholder was created with this same turn id, so there is
        // nothing to swap -- `run_started` only confirms it.
        this.streamingId = `assistant:${event.turn_id}`
        return false
      }

      case "thinking_delta": {
        if (!id) return false
        this.update(id, (m) => {
          const last = m.parts[m.parts.length - 1]
          if (last?.kind === "reasoning") {
            return {
              ...m,
              parts: [
                ...m.parts.slice(0, -1),
                { kind: "reasoning", text: last.text + event.text },
              ],
            }
          }
          return { ...m, parts: [...m.parts, { kind: "reasoning", text: event.text }] }
        })
        return false
      }

      case "text_delta": {
        if (!id) return false
        // Consecutive text deltas merge into one part, otherwise a 400-token
        // answer becomes 400 DOM nodes.
        this.update(id, (m) => {
          const last = m.parts[m.parts.length - 1]
          if (last?.kind === "text") {
            return {
              ...m,
              parts: [...m.parts.slice(0, -1), {
                kind: "text",
                text: last.text + event.text,
              }],
            }
          }
          return { ...m, parts: [...m.parts, { kind: "text", text: event.text }] }
        })
        return false
      }

      case "tool_start": {
        if (!id) return false
        this.appendTo(id, {
          kind: "tool",
          id: event.id,
          name: event.name,
          args: event.args,
          status: "running",
          text: "",
        })
        return false
      }

      case "tool_args_delta": {
        if (!id) return false
        // A long command types itself out; show the arguments as they land.
        this.update(id, (m) => ({
          ...m,
          parts: m.parts.map((part) =>
            part.kind === "tool" && part.id === event.id
              ? { ...part, args: event.args }
              : part,
          ),
        }))
        return false
      }

      case "tool_end": {
        if (!id) return false
        this.update(id, (m) => ({
          ...m,
          parts: m.parts.map((part) =>
            part.kind === "tool" && part.id === event.id
              ? {
                  ...part,
                  status: event.status === "error" ? "error" : "success",
                  text: event.text,
                }
              : part,
          ),
        }))
        return false
      }

      case "usage": {
        // Reported per model call, so the last one wins; with a tool loop that
        // is the final call, which is the only one worth attributing to the
        // turn. `reported === 0` is the backend's way of saying "the model
        // reported nothing", and it is carried through rather than rounded to
        // a confident zero.
        this.set({
          usage: {
            input: event.input,
            output: event.output,
            total: event.total,
            unreported: event.reported === 0,
          },
        })
        return false
      }

      case "done":
        void this.finish(event.status, null)
        return true

      case "error":
        void this.finish(event.status, event.message)
        return true
    }
  }

  /**
   * The backend's status strings are the same set the store persists, but the
   * `done`/`error` events arrive as plain strings across the wire. Coerced here
   * so one bad status string degrades to "failed" rather than corrupting a
   * transcript.
   */
  private async finish(rawStatus: string, error: string | null) {
    const status = (
      ["running", "completed", "failed", "cancelled", "interrupted"] as const
    ).includes(rawStatus as TurnView["status"])
      ? (rawStatus as TurnView["status"])
      : "failed"
    const id = this.streamingId
    if (id) {
      this.update(id, (m) => ({ ...m, running: false, status }))
    }
    this.set({
      busy: false,
      runId: null,
      error: error ?? this.state.error,
      turns: this.state.turns.map((t) =>
        t.status === "running" ? { ...t, status } : t,
      ),
    })
    // Re-read the path so version numbers and statuses come from the database
    // rather than from what this client happened to observe.
    await this.refreshChat().catch(() => undefined)

    // And the chat list, because the backend names a chat after its first
    // question -- a title that did not exist when this client created the chat.
    // Without this the sidebar shows a new conversation as a blank row until
    // the page is reloaded.
    try {
      this.set({ chats: await api.listChats() })
    } catch {
      /* the transcript is what matters; a stale sidebar is not worth an error */
    }
  }

  private stop() {
    this.streamGeneration += 1
    this.stream?.close()
    this.stream = null
    this.streamingId = null
  }

  dispose() {
    this.stop()
    this.listeners.clear()
  }
}

// ------------------------------------------------------------ projection --

function optimisticTurn(
  id: string,
  user_text: string,
  files: ChatFile[],
): TurnView {
  return {
    id,
    user_text,
    files,
    status: "running",
    created_at: Date.now(),
    snapshot: null,
    version: 0,
    version_count: 1,
  }
}

function userMessage(turn: TurnView): AtlasMessage {
  return {
    id: `user:${turn.id}`,
    role: "user",
    turnId: turn.id,
    files: turn.files,
    parts: turn.user_text
      ? [{ kind: "text", text: turn.user_text }]
      : [],
    running: false,
    status: turn.status,
    createdAt: turn.created_at,
  }
}

/**
 * Rebuild one assistant message from the backend's stored messages.
 *
 * Stored messages are `text`, `tool_use` and `tool_result`, so reasoning cannot
 * be recovered -- it is deliberately never persisted (S13). That is why a
 * reloaded chat shows answers and tool activity but no thinking above them.
 */
async function assistantMessage(
  chatId: string,
  turn: TurnView,
): Promise<AtlasMessage> {
  const createdAt = turn.created_at
  const message: AtlasMessage = {
    id: `assistant:${turn.id}`,
    role: "assistant",
    turnId: turn.id,
    files: [],
    parts: [],
    running: turn.status === "running",
    status: turn.status,
    createdAt,
  }
  if (!turn.snapshot) return message

  try {
    const { messages } = await api.getTurn(chatId, turn.id)
    for (const stored of messages) {
      if (stored.kind === "text" && stored.text) {
        // **Only the assistant's own text.** A turn's snapshot contains the whole
        // exchange, so `getTurn` also returns the user's prompt with
        // `role: "user"`. Taking every text block printed the question above the
        // answer to it -- once during the run, and again on every reload, because
        // this is the path that rebuilds a finished turn.
        if (stored.role !== "assistant") continue
        message.parts.push({ kind: "text", text: stored.text })
      } else if (stored.kind === "tool_use" && stored.name) {
        // No toolUseId survives persistence, so the id is synthesised from the
        // tool name and its position. It only has to be unique within the turn.
        message.parts.push({
          kind: "tool",
          id: `${stored.name}:${message.parts.length}`,
          name: stored.name,
          args: stored.input ?? {},
          status: "running",
          text: "",
        })
      } else if (stored.kind === "tool_result") {
        const last = message.parts[message.parts.length - 1]
        if (last?.kind === "tool") {
          last.status = stored.status === "error" ? "error" : "success"
          last.text = stored.text ?? ""
        }
      }
    }
  } catch {
    // A turn whose snapshot cannot be read still renders as a message with no
    // content. Better than dropping the turn from the transcript silently.
  }
  return message
}

// -------------------------------------------------------------- singleton --

export const atlas = new AtlasStore()

export function useAtlas(): AtlasState {
  return useSyncExternalStore(atlas.subscribe, atlas.getSnapshot)
}

export function useAtlasActions() {
  return useCallback(
    () => ({
      send: atlas.send.bind(atlas),
      retry: atlas.retry.bind(atlas),
      edit: atlas.edit.bind(atlas),
      selectVersion: atlas.selectVersion.bind(atlas),
      cancel: atlas.cancel.bind(atlas),
      newChat: atlas.newChat.bind(atlas),
      openChat: atlas.openChat.bind(atlas),
      deleteChat: atlas.deleteChat.bind(atlas),
      init: atlas.init.bind(atlas),
      refreshSettings: atlas.refreshSettings.bind(atlas),
      saveSettings: atlas.saveSettings.bind(atlas),
    }),
    [],
  )()
}
