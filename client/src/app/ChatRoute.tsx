import { useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { atlas, useAtlas } from "@/state/store"
import { ChatScreen } from "@/features/chat/ChatScreen"

/** Keeps the URL and the open chat in step, in both directions. */
export function ChatRoute() {
  const { chatId } = useParams()
  const navigate = useNavigate()
  const openId = useAtlas((s) => s.chat?.id ?? null)

  useEffect(() => {
    if (chatId) void atlas.openChat(chatId)
    else if (atlas.state.chat) atlas.newChat()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId])

  // A first message creates the chat: move the URL to it.
  useEffect(() => {
    if (!chatId && openId) navigate(`/c/${openId}`, { replace: true })
  }, [chatId, openId, navigate])

  return <ChatScreen />
}
