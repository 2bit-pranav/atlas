/**
 * "2 min ago" for messages. One shared 30-second timer, however many messages
 * are on screen, so the labels move on without a timer each.
 */
import { useSyncExternalStore } from "react"

const listeners = new Set<() => void>()
let now = Date.now()
let timer: ReturnType<typeof setInterval> | null = null

function subscribe(listener: () => void) {
  listeners.add(listener)
  if (!timer) {
    timer = setInterval(() => {
      now = Date.now()
      listeners.forEach((l) => l())
    }, 30_000)
  }
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }
}

/** The current time, updated every 30 seconds. */
export function useNow(): number {
  return useSyncExternalStore(subscribe, () => now)
}

const DAY = 86_400_000

/** `then` (epoch ms) relative to `current`: just now, 5 min ago, 3 h ago, yesterday, 4 days ago, 12 Oct. */
export function timeAgo(then: number, current: number): string {
  const diff = Math.max(0, current - then)
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  const startOfToday = new Date(current).setHours(0, 0, 0, 0)
  if (then >= startOfToday) return `${Math.floor(minutes / 60)} h ago`
  if (then >= startOfToday - DAY) return "yesterday"
  const days = Math.ceil((startOfToday - then) / DAY)
  if (days < 7) return `${days} days ago`
  const date = new Date(then)
  return date.toLocaleDateString(undefined, {
    day: "numeric", month: "short",
    year: date.getFullYear() === new Date(current).getFullYear() ? undefined : "numeric",
  })
}

/** The same, as short as a task list needs: now, 12m, 3h, yest., Tue, 12 Oct. */
export function shortAgo(then: number, current: number): string {
  const minutes = Math.floor(Math.max(0, current - then) / 60_000)
  if (minutes < 1) return "now"
  if (minutes < 60) return `${minutes}m`
  const startOfToday = new Date(current).setHours(0, 0, 0, 0)
  if (then >= startOfToday) return `${Math.floor(minutes / 60)}h`
  if (then >= startOfToday - DAY) return "yest."
  const date = new Date(then)
  return then >= startOfToday - 6 * DAY
    ? date.toLocaleDateString(undefined, { weekday: "short" })
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short" })
}

/** "0:41", "12:05": a run's length. */
export const clock = (ms: number) => {
  const s = Math.round(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

/** The exact time, for a tooltip. */
export function fullTime(then: number): string {
  return new Date(then).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
}
