/**
 * Display preferences: per browser, never sent to the backend.
 *
 * Kept apart from settings.json on purpose. Those settings change what the
 * agent does; these change only how this browser shows it, and two browsers
 * pointed at the same Atlas can reasonably disagree about them.
 */

import { useSyncExternalStore } from "react"

export interface Prefs {
  theme: "system" | "light" | "dark"
  sendOnEnter: boolean
  showStats: boolean
  expandReasoning: boolean
  expandTools: boolean
  showContextMeter: boolean
  autoScroll: boolean
  /** Shows the tuning settings, the extension's pairing token and build steps. */
  devMode: boolean
}

const KEY = "atlas-prefs"
const DEFAULTS: Prefs = {
  theme: "system",
  sendOnEnter: true,
  showStats: true,
  expandReasoning: false,
  expandTools: false,
  showContextMeter: true,
  autoScroll: false,
  devMode: false,
}

function load(): Prefs {
  try {
    return { ...DEFAULTS, ...(JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>) }
  } catch {
    return DEFAULTS
  }
}

let prefs = load()
const listeners = new Set<() => void>()

export function setPrefs(patch: Partial<Prefs>) {
  prefs = { ...prefs, ...patch }
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    /* private window: keep it for this session */
  }
  applyTheme()
  listeners.forEach((l) => l())
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => prefs,
  )
}

const media = window.matchMedia("(prefers-color-scheme: dark)")

export function applyTheme() {
  const dark = prefs.theme === "dark" || (prefs.theme === "system" && media.matches)
  document.documentElement.classList.toggle("dark", dark)
}

media.addEventListener("change", applyTheme)
applyTheme()
