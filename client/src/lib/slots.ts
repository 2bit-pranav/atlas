/**
 * Places where a host of the shared chat components adds its own UI.
 *
 * The browser extension renders the shared `Messages`; under each finished
 * answer it shows the page passages the answer quoted (found or not), which
 * the web UI has no use for. Without a provider the slot renders nothing.
 */
import { createContext, type ReactNode } from "react"

import type { Turn } from "@/lib/types"

/** Rendered under an answer: `(turn, answer text) => node`. */
export const AnswerExtras = createContext<((turn: Turn, answer: string) => ReactNode) | null>(null)
