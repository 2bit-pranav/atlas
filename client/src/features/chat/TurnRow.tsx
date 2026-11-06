import { memo, useState } from "react"
import type { Part, Turn, TurnStats } from "@/api/types"
import { UserMessage } from "@/features/chat/UserMessage"
import { AssistantMessage } from "@/features/chat/AssistantMessage"

// ------------------------------------------------------------------ turn --

export const TurnRow = memo(function TurnRow({ turn, chatId, isLast, laterCount, liveParts, liveStats }: {
  turn: Turn
  chatId: string
  isLast: boolean
  /** How many turns come after this one: what an edit here would delete. */
  laterCount: number
  liveParts: Part[] | null
  liveStats: TurnStats | null
}) {
  const [editing, setEditing] = useState(false)
  const parts = liveParts ?? turn.render
  const running = turn.status === "running"
  return (
    <div className="w-full" data-turn-id={turn.id}>
      <UserMessage turn={turn} chatId={chatId} editing={editing} setEditing={setEditing} laterCount={laterCount}
                   parts={parts} stats={liveStats ?? turn.stats} />
      <AssistantMessage turn={turn} chatId={chatId} parts={parts} stats={liveStats ?? turn.stats} running={running} isLast={isLast} />
    </div>
  )
})
