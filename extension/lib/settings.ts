/**
 * The extension's own settings, in `storage.local`. Only what the extension
 * needs; everything about the agent stays in the web UI.
 */

export interface ExtensionSettings {
  /** The Atlas backend. */
  base: string
  /** From Atlas > Settings > Browser extension. */
  token: string
  /** Sites Atlas never reads (one host per line; `*.bank.com` covers subdomains). */
  neverRead: string[]
  /** Where "Save table" puts files. Empty: Downloads/Atlas. */
  tablesFolder: string
  /** Languages offered by "Translate" in the selection chip; the first is the default. */
  languages: string[]
}

export const DEFAULTS: ExtensionSettings = {
  base: "http://127.0.0.1:8000",
  token: "",
  neverRead: [],
  tablesFolder: "",
  languages: ["English", "Hindi", "Marathi"],
}

export async function loadSettings(): Promise<ExtensionSettings> {
  const stored = await browser.storage.local.get("settings")
  return { ...DEFAULTS, ...(stored.settings as Partial<ExtensionSettings> | undefined) }
}

export async function saveSettings(patch: Partial<ExtensionSettings>): Promise<ExtensionSettings> {
  const next = { ...(await loadSettings()), ...patch }
  await browser.storage.local.set({ settings: next })
  return next
}

/** True when `url` is on the never-read list, or not a web page at all. */
export function blocked(url: string | undefined, neverRead: string[]): string | null {
  if (!url) return "no page"
  let host: string
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "not a web page"
    host = parsed.hostname
  } catch {
    return "not a web page"
  }
  for (const raw of neverRead) {
    const rule = raw.trim().toLowerCase()
    if (!rule) continue
    const bare = rule.replace(/^\*\./, "")
    if (host === bare || host.endsWith(`.${bare}`)) return `${host} is on your never-read list`
  }
  return null
}

/** A selection-chip or context-menu request, waiting for the panel to pick it up. */
export interface PendingAsk {
  action: "explain" | "simplify" | "define" | "translate" | "ask" | "image"
  text: string
  /** An image's address, for "Ask Atlas about this image". */
  src?: string
  language?: string
  tabId: number
  at: number
}
