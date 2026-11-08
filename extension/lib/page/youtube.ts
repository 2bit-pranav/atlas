/**
 * A YouTube video, for questions about it: its title, channel, length,
 * description and transcript, each line with its time.
 *
 * The transcript is read from the panel YouTube itself shows ("Show
 * transcript"), opened if it is not: YouTube's caption files now need a token
 * only its player can make, and come back empty without one. A video with no
 * captions has only its description.
 */

export const isYouTubeVideo = (href = location.href) => {
  try {
    const url = new URL(href)
    return /(^|\.)youtube\.com$/.test(url.hostname) && ((url.pathname === "/watch" && url.searchParams.has("v")) || url.pathname.startsWith("/shorts/"))
  } catch {
    return false
  }
}

const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim()
/** An element's text with its line breaks kept (innerText: what is shown; jsdom has only textContent). */
const textLines = (el: HTMLElement | null) =>
  (el?.innerText || el?.textContent || "").split("\n").map(clean).filter(Boolean).join("\n")
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** "12:34" or "1:02:03" in seconds. */
export function seconds(stamp: string): number {
  return stamp.split(":").map(Number).reduce((total, part) => total * 60 + part, 0)
}

export function clockOf(total: number): string {
  const s = Math.floor(total % 60), m = Math.floor(total / 60) % 60, h = Math.floor(total / 3600)
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`
}

const SEGMENTS = "ytd-transcript-segment-renderer, transcript-segment-view-model"
const STAMP = /^\s*(\d{1,2}(?::\d{2}){1,2})\s*/

/**
 * The transcript on the page as passages of about `size` characters, each
 * with the time it starts: "[0:04] This is a three. It's sloppily written…".
 * YouTube's own lines are 2-3 seconds each; one time per line tripled the
 * text the model reads, for nothing.
 */
export function transcriptLines(root: ParentNode = document, size = 300): string[] {
  const out: string[] = []
  let stampOf = ""
  let words = ""
  const flush = () => {
    if (words) out.push(stampOf ? `[${stampOf}] ${words}` : words)
    words = ""
    stampOf = ""
  }
  let last = -1
  for (const seg of Array.from(root.querySelectorAll(SEGMENTS))) {
    const stampEl = seg.querySelector(".segment-timestamp, [class*='Timestamp'], [class*='timestamp']")
    const all = clean(seg.textContent)
    const stamp = clean(stampEl?.textContent) || STAMP.exec(all)?.[1] || ""
    const text = clean(stampEl ? all.replace(clean(stampEl.textContent), "") : all.replace(STAMP, ""))
    if (!text) continue
    // YouTube can keep two copies of the transcript in the page (one per layout): where the
    // times start over, the second copy has begun.
    if (stamp) {
      const at = seconds(stamp)
      if (at + 1 < last) break
      last = at
    }
    if (!words) stampOf = stamp
    words = words ? `${words} ${text}` : text
    if (words.length >= size) flush()
  }
  flush()
  return out
}

/** Open YouTube's own transcript panel and wait for its lines (up to ~6 s). */
/** Wait up to `ms` for `find` to give something: YouTube builds the page after it loads. */
async function until<T>(find: () => T | null | undefined, ms: number): Promise<T | null> {
  for (let waited = 0; ; waited += 200) {
    const found = find()
    if (found || waited >= ms) return found ?? null
    await wait(200)
  }
}

async function openTranscript(): Promise<boolean> {
  if (document.querySelector(SEGMENTS)) return true
  // The button sits in the description, which may be collapsed.
  document.querySelector<HTMLElement>("#description-inline-expander #expand, ytd-text-inline-expander #expand")?.click()
  const button = await until(() => Array.from(document.querySelectorAll<HTMLElement>("ytd-video-description-transcript-section-renderer button, button"))
    .find((b) => /show transcript/i.test(`${b.textContent ?? ""} ${b.getAttribute("aria-label") ?? ""}`)), 3000)
  if (!button) return false
  button.click()
  for (let i = 0; i < 30; i++) {
    await wait(200)
    if (document.querySelector(SEGMENTS)) return true
  }
  return false
}

/** The video's id from its address (watch?v=, /shorts/, /live/), or "". */
export function videoId(url: string): string {
  try {
    const u = new URL(url)
    return u.searchParams.get("v") ?? /^\/(?:shorts|live)\/([\w-]+)/.exec(u.pathname)?.[1] ?? ""
  } catch {
    return ""
  }
}

/**
 * The last video read, kept for the next message: reading it opens the
 * transcript panel and waits for it (and for a video without captions, waits
 * 3 s for a button that never comes), seconds before each message went.
 * Kept only when the page shows that video (YouTube changes videos without
 * reloading, and its old details linger for a moment after the address changes).
 */
let kept: { id: string; read: { title: string; content: string } } | null = null

export async function youtube(): Promise<{ title: string; content: string }> {
  const id = videoId(location.href)
  if (id && kept?.id === id) return kept.read
  const read = await readVideo()
  if (id && document.querySelector("ytd-watch-flexy")?.getAttribute("video-id") === id) kept = { id, read }
  return read
}

async function readVideo(): Promise<{ title: string; content: string }> {
  // The video's details arrive after the page itself.
  await until(() => document.querySelector("ytd-watch-metadata ytd-text-inline-expander, #owner #channel-name"), 5000)
  const title = clean(document.querySelector("h1.ytd-watch-metadata, #title h1, h1.title")?.textContent) ||
    document.title.replace(/\s+-\s+YouTube$/, "")
  const channel = clean(document.querySelector("#owner #channel-name a, ytd-channel-name a")?.textContent)
  const lines = (await openTranscript()) ? transcriptLines() : []
  // While an ad plays, the video element is the ad: its length is the transcript's last time instead.
  const video = document.querySelector("video")
  const ad = Boolean(document.querySelector("#movie_player.ad-showing"))
  const lastStamp = /^\[([\d:]+)\]/.exec(lines.at(-1) ?? "")?.[1]
  const length = video && !ad && Number.isFinite(video.duration) ? clockOf(video.duration) : lastStamp ? `about ${lastStamp}` : ""
  // The first match in page order is an empty "#description"; the text is in the inline expander.
  // Line by line: a chapter list ("0:00 Intro") is one line per chapter (agent/extension/moments.py).
  const described = ["ytd-text-inline-expander", "#description-inline-expander", "ytd-expandable-video-description-body-renderer"]
    .map((sel) => textLines(document.querySelector<HTMLElement>(sel))).find(Boolean) ?? ""
  const description = described.slice(0, 3000)
  const content = [
    `# ${title}`,
    [channel && `Channel: ${channel}`, length && `Length: ${length}`].filter(Boolean).join(" · "),
    description && `## Description\n${description}`,
    lines.length ? `## Transcript\n${lines.join("\n")}` : "## Transcript\n(none: this video has no captions, so only its description can be used)",
  ].filter(Boolean).join("\n\n")
  return { title, content }
}

/** Play the video from `at` seconds. */
export function playFrom(at: number): boolean {
  const video = document.querySelector("video")
  if (!video) return false
  video.currentTime = at
  // Not always a promise (older engines, test DOMs): never let a refused autoplay throw.
  const started = video.play() as Promise<void> | undefined
  started?.catch?.(() => undefined)
  video.scrollIntoView?.({ behavior: "smooth", block: "center" })
  return true
}
