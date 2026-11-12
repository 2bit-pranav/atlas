/**
 * The extension's own settings, in `storage.local`. Only what the extension
 * needs; everything about the agent stays in the web UI.
 */

export interface ExtensionSettings {
    base: string;
    token: string;
    neverRead: string[];
    tablesFolder: string;
    languages: string[];
}

export const DEFAULTS: ExtensionSettings = {
    base: "http://127.0.0.1:8000",
    token: "",
    neverRead: [],
    tablesFolder: "",
    languages: ["English", "Hindi", "Marathi"],
};

/** What a content script may know: everything but the pairing token. */
export type PageSettings = Omit<ExtensionSettings, "token">;

/**
 * For the worker and the extension's own pages only. The token is kept under
 * its own key (`pairing`), apart from the settings a content script needs, and
 * `lockStorage` closes the whole area to content scripts: they run inside web
 * pages, and one that a page took over could read the token from storage, and
 * with it every chat (2026-11-12). They ask the worker instead (`loadPageSettings`).
 */
export async function loadSettings(): Promise<ExtensionSettings> {
    const stored = await browser.storage.local.get(["settings", "pairing"]);
    const settings = (stored.settings ?? {}) as Partial<ExtensionSettings>;
    const pairing = stored.pairing as { token?: string } | undefined;
    // An install from before the split kept the token inside `settings`.
    return { ...DEFAULTS, ...settings, token: pairing?.token ?? settings.token ?? "" };
}

export async function saveSettings(
    patch: Partial<ExtensionSettings>,
): Promise<ExtensionSettings> {
    const next = { ...(await loadSettings()), ...patch };
    await browser.storage.local.set({ settings: pageSettings(next), pairing: { token: next.token } });
    return next;
}

export function pageSettings(settings: ExtensionSettings): PageSettings {
    const { token: _token, ...rest } = settings;
    return rest;
}

/** Storage is for the worker and the extension's pages, not for content scripts. Called when the worker starts. */
export function lockStorage(): void {
    const area = browser.storage.local as unknown as {
        setAccessLevel?: (level: { accessLevel: string }) => Promise<void>;
    };
    void area.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" })?.catch(() => undefined);
}

/** A content script's settings, from the worker: storage is closed to it. */
export async function loadPageSettings(): Promise<PageSettings> {
    try {
        const answer = (await browser.runtime.sendMessage({ type: "atlas:settings" })) as Partial<PageSettings> | undefined;
        return { ...pageSettings(DEFAULTS), ...answer };
    } catch {
        return pageSettings(DEFAULTS);
    }
}

/** An address on this computer over plain http: the only place Atlas runs, and the only page that may pair the extension. */
export function localHttp(url: string | undefined): boolean {
    try {
        const parsed = new URL(url ?? "");
        return (
            parsed.protocol === "http:" &&
            ["127.0.0.1", "localhost"].includes(parsed.hostname)
        );
    } catch {
        return false;
    }
}

/**
 * Whether `base` is the Atlas the extension is set to (same scheme, host
 * and port). A page may pair only with that one: any local port would let a
 * page on another port point the extension, and what it reads, at its own server.
 * Another address is set in the extension's own Settings, which no page reaches.
 */
export function samePlace(configured: string, base: string): boolean {
    try {
        return new URL(configured).origin === new URL(base).origin;
    } catch {
        return false;
    }
}

/** True when `url` is on the never-read list, or not a web page at all. */
export function blocked(
    url: string | undefined,
    neverRead: string[],
): string | null {
    if (!url) return "no page";
    let host: string;
    try {
        const parsed = new URL(url);
        if (!["http:", "https:", "file:"].includes(parsed.protocol))
            return "not a web page";
        host = parsed.hostname;
    } catch {
        return "not a web page";
    }
    for (const raw of neverRead) {
        const rule = raw.trim().toLowerCase();
        if (!rule) continue;
        const bare = rule.replace(/^\*\./, "");
        if (host === bare || host.endsWith(`.${bare}`))
            return `${host} is on your never-read list`;
    }
    return null;
}

/** A selection-chip or context-menu request, waiting for the panel to pick it up. */
export interface PendingAsk {
    action: "explain" | "simplify" | "define" | "translate" | "ask" | "image";
    text: string;
    /** An image's address, for "Ask Atlas about this image". */
    src?: string;
    language?: string;
    tabId: number;
    at: number;
}
