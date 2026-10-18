/**
 * Keyboard shortcuts, after llama.cpp's web UI (`use-keyboard-shortcuts`).
 * Ctrl stands for Cmd on macOS. One table, read by both the handler in
 * `App.tsx` and the Shortcuts settings page, so the list cannot drift.
 */

export type ShortcutAction =
  | "search" | "toggleSidebar" | "newChat" | "renameChat" | "deleteChat"
  | "exportChat" | "prevChat" | "nextChat" | "settings"

export interface Shortcut {
  action: ShortcutAction
  label: string
  keys: string[]
  key: string
  shift: boolean
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)
const MOD = isMac ? "⌘" : "Ctrl"

const s = (action: ShortcutAction, label: string, key: string, shift: boolean, shown: string): Shortcut => ({
  action, label, key, shift, keys: [MOD, ...(shift ? ["Shift"] : []), shown],
})

export const SHORTCUTS: Shortcut[] = [
  s("newChat", "New chat", "o", true, "O"),
  s("search", "Search conversations", "k", false, "K"),
  s("toggleSidebar", "Toggle sidebar", "b", false, "B"),
  s("renameChat", "Rename conversation", "e", true, "E"),
  s("exportChat", "Export conversation", "s", true, "S"),
  s("deleteChat", "Delete conversation", "d", true, "D"),
  s("prevChat", "Previous conversation", "arrowup", true, "↑"),
  s("nextChat", "Next conversation", "arrowdown", true, "↓"),
  s("settings", "Open settings", ",", false, ","),
]

export function matchShortcut(e: KeyboardEvent): ShortcutAction | null {
  const mod = isMac ? e.metaKey : e.ctrlKey
  if (!mod || e.altKey) return null
  const key = e.key.toLowerCase()
  const hit = SHORTCUTS.find((x) => x.key === key && x.shift === e.shiftKey)
  return hit?.action ?? null
}

export const shortcutKeys = (action: ShortcutAction) => SHORTCUTS.find((x) => x.action === action)?.keys ?? []
