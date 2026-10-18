/**
 * assistant-ui binding.
 *
 * assistant-ui already solves the half of chat that is not Atlas: message
 * threading, the composer, markdown, tool-call rendering, edit and regenerate
 * affordances. It also accepts an *external store*, which is what we need --
 * Atlas's messages come from a Strands snapshot over SSE, not from a
 * provider's React SDK, and nothing about that is assistant-ui's business.
 *
 * So this file owns the seam and nothing else. The division:
 *
 *   atlasStore   what is true      (SSE, resumption, the chat tree)
 *   this file    what it looks like (AtlasMessage -> assistant-ui parts)
 *
 * Two conversions that are not mechanical:
 *
 * - **Reasoning** becomes a `data-` part, not text. It must render inside a
 *   collapsible and must never end up in the answer's markdown.
 * - **Tool calls** become real `tool-call` parts with a real `result`, so
 *   assistant-ui's own `ToolFallback` renders them and its status handling works.
 */

import { useExternalStoreRuntime } from "@assistant-ui/react"
import type {
  ExternalStoreAdapter,
  ThreadMessageLike,
} from "@assistant-ui/react"

import { downloadUrl } from "@/services/atlasApi"
import { atlas, useAtlas, type AtlasMessage, type MessagePart } from "./atlasStore"
import type { ChatFile, TurnView } from "@/types/api"

/**
 * Reasoning is rendered by our own component rather than a markdown block, so
 * it gets a `data-` prefixed part. assistant-ui routes `data-reasoning` to the
 * `Reasoning` component registered on the provider.
 */
type ReasoningPart = { type: "data-reasoning"; data: { text: string } }

function convertParts(parts: MessagePart[]): ThreadMessageLike["content"] {
  const out: Record<string, unknown>[] = []

  for (const part of parts) {
    switch (part.kind) {
      case "text":
        // Empty text parts are dropped: an assistant message that has only
        // started streaming should not render a stray empty markdown block.
        if (part.text.trim()) out.push({ type: "text", text: part.text })
        break

      case "reasoning":
        if (part.text)
          out.push({ type: "data-reasoning", data: { text: part.text } })
        break

      case "tool":
        out.push({
          type: "tool-call",
          // Synthetic ids from the persisted projection are namespaced so they
          // cannot collide with a live `toolUseId` after a reload mid-run.
          toolCallId: part.id,
          toolName: part.name || "tool",
          args: (part.args ?? {}) as Record<string, unknown>,
          result: part.status === "running" ? undefined : { text: part.text },
          isError: part.status === "error",
        })
        break
    }
  }
  return out as unknown as ThreadMessageLike["content"]
}

function convertMessage(
  message: AtlasMessage,
  turn: TurnView | undefined,
): ThreadMessageLike {
  const chatId = atlas.getSnapshot().chatId
  const isUser = message.role === "user"
  return {
    id: message.id,
    role: message.role,
    content: convertParts(message.parts),
    createdAt: new Date(message.createdAt),
    // **Assistant messages only.** assistant-ui's `fromThreadMessageLike` throws
    // `"status is only supported for assistant messages"`, and because that
    // throw happens inside `convertMessages` it takes the entire thread down
    // rather than skipping one message -- so a `status` on a user message blanked
    // the whole app on the very first send, with a console error naming nothing
    // the user could act on.
    //
    // `reason` is required on completion. "unknown" rather than "stop": the
    // backend reports the run's status, not a provider's finish reason, and
    // claiming a clean stop would be a detail nobody asked for and cannot verify.
    status: isUser
      ? undefined
      : message.running
        ? { type: "running" as const }
        : { type: "complete" as const, reason: "unknown" as const },
    // The backend serves the bytes back verbatim; nothing was parsed at upload,
    // so a link to the saved file is the only honest thing to show.
    attachments: isUser
      ? message.files.map((file) => ({
          id: file.path,
          type: "file" as const,
          name: file.name,
          contentType: file.type,
          status: { type: "complete" as const },
          url: chatId ? downloadUrl(chatId, file.name) : undefined,
          content: [],
        }))
      : undefined,
  }
}

/**
 * The per-turn footer rides as a `data-turn` part rather than as a child
 * element, because assistant-ui's row components are given no props -- there is
 * no supported way to hand a row its turn id. A data part carries the payload
 * to the renderer that needs it, and it costs nothing when absent.
 */
function withTurnFooter(message: AtlasMessage): ThreadMessageLike {
  const converted = convertMessage(message, undefined)
  if (message.role === "user") return converted
  const turn = atlas
    .getSnapshot()
    .turns.find((t) => t.id === message.turnId)
  if (!turn) return converted
  const parts = converted.content as unknown as Record<string, unknown>[]
  return {
    ...converted,
    content: [
      ...parts,
      {
        type: "data-turn",
        data: {
          turnId: turn.id,
          version: turn.version,
          versionCount: turn.version_count,
          status: turn.status,
          usage: atlas.getSnapshot().usage,
        },
      },
    ] as unknown as ThreadMessageLike["content"],
  }
}

/**
 * The adapter. Rebuilt on every state change, which is how assistant-ui is
 * designed to work: it diffs `messages` by id and keeps scroll position, so
 * rebuilding the object is cheap and mutating it would be wrong.
 */
function adapter(): ExternalStoreAdapter<AtlasMessage> {
  const state = atlas.getSnapshot()

  return {
    messages: state.messages,
    convertMessage: withTurnFooter,
    isRunning: state.busy,
    isDisabled: false,

    onNew: async (message) => {
      // Text only. The attachments are already in the store, and `send` reads
      // them itself -- passing them here from a second owner is how they were
      // being dropped.
      await atlas.send(extractText(message))
    },

    onEdit: async (message) => {
      // `onEdit` fires for a user message being edited. The turn being edited
      // is that message's own turn, and the edit mints a sibling of it.
      const turnId = turnOf((message as { id?: string }).id ?? "")
      if (turnId) await atlas.edit(turnId, extractText(message))
    },

    onReload: async (parentId) => {
      if (parentId) await atlas.retry(parentId)
    },

    onCancel: async () => {
      await atlas.cancel()
    },

    onRefetchThread: async () => {
      if (state.chatId) await atlas.openChat(state.chatId)
    },

    adapters: {
      threadList: {
        threads: state.chats.map((chat) => ({
          id: chat.id,
          remoteId: chat.id,
          title: chat.title || "Untitled",
          status: "regular" as const,
        })),
        onSwitchToThread: async (id: string) => {
          await atlas.openChat(id)
        },
        onSwitchToNewThread: async () => {
          await atlas.newChat()
        },
        onDelete: async (id: string) => {
          await atlas.deleteChat(id)
        },
      },
    },
  }
}

// ------------------------------------------------------------- id helpers --
//
// Message ids are `user:<turn>` and `assistant:<turn>`. The two operations that
// need a turn id want different ones, and guessing wrong here means retrying a
// message instead of the turn it belongs to.

const idPattern = /^(user|assistant):(.+)$/

function turnOf(messageId: string): string | null {
  const match = idPattern.exec(messageId)
  return match ? match[2] : null
}

function extractText(message: { content?: unknown }): string {
  if (typeof message.content === "string") return message.content
  if (!Array.isArray(message.content)) return ""
  return message.content
    .filter(
      (part): part is { type: "text"; text: string } =>
        typeof part === "object" &&
        part !== null &&
        (part as { type?: string }).type === "text",
    )
    .map((part) => part.text)
    .join("")
}

// ------------------------------------------------------------------- hooks --

export function useAtlasRuntime() {
  // Subscribing first is what makes this re-render on every SSE delta; the
  // returned runtime is rebuilt from the fresh state each time.
  useAtlas()
  return useExternalStoreRuntime<AtlasMessage>(adapter())
}

/** Re-exported so components can type the turn list without a second import. */
export type { TurnView }
