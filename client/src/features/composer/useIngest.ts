import { useEffect, useState } from "react"
import * as api from "@/api/client"
import type { IngestStatus } from "@/api/types"

const DONE = new Set(["ready", "failed"])

/** Parsing progress of the attachments named, polled once a second until each is ready or failed. */
export function useIngest(chatId: string | null | undefined, names: string[]): Record<string, IngestStatus> {
  const [status, setStatus] = useState<Record<string, IngestStatus>>({})
  const key = names.join("\n")

  useEffect(() => {
    if (!chatId || !key) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const next = await api.ingestStatus(chatId, key.split("\n"))
        if (stopped) return
        setStatus(next)
        if (Object.values(next).every((s) => DONE.has(s.status))) return
      } catch {
        if (stopped) return   // a missed poll is retried; the chip just shows the last state
      }
      timer = setTimeout(tick, 1000)
    }
    void tick()
    return () => { stopped = true; clearTimeout(timer) }
  }, [chatId, key])

  return status
}
