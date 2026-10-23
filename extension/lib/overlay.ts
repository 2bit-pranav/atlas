/**
 * What Atlas draws on the page itself: the selection chip, the "Save table"
 * button, and a short toast. Plain DOM in one shadow root, so the page's CSS
 * cannot reach it and the content script stays small (no React here).
 */

const STYLE = `
:host { all: initial; }
.box { position: fixed; z-index: 2147483647; font: 12px/1.3 system-ui, -apple-system, "Segoe UI", sans-serif;
  display: flex; gap: 2px; padding: 3px; border-radius: 10px; background: #171717; color: #fafafa;
  box-shadow: 0 4px 14px rgb(0 0 0 / .25); align-items: center; }
.box button, .box select { all: unset; cursor: pointer; padding: 4px 8px; border-radius: 7px; color: inherit; }
.box button:hover, .box select:hover { background: #333; }
.box .logo { font-weight: 600; padding: 4px 6px 4px 8px; color: #a3a3a3; }
.box select option { color: #171717; }
.toast { position: fixed; z-index: 2147483647; right: 16px; bottom: 16px; max-width: 360px; padding: 10px 12px;
  border-radius: 10px; background: #171717; color: #fafafa; font: 12px/1.4 system-ui, sans-serif;
  box-shadow: 0 4px 14px rgb(0 0 0 / .25); }
.toast.error { background: #7f1d1d; }
`

let root: ShadowRoot | null = null

export function shadow(): ShadowRoot {
  if (root) return root
  const host = document.createElement("div")
  host.id = "atlas-ui-root"
  document.documentElement.appendChild(host)
  root = host.attachShadow({ mode: "closed" })
  const style = document.createElement("style")
  style.textContent = STYLE
  root.appendChild(style)
  return root
}

export function box(x: number, y: number): HTMLDivElement {
  const el = document.createElement("div")
  el.className = "box"
  el.style.left = `${Math.max(8, Math.min(x, innerWidth - 340))}px`
  el.style.top = `${Math.max(8, Math.min(y, innerHeight - 44))}px`
  // Clicks inside must not clear the page's selection or reach the page.
  el.addEventListener("mousedown", (e) => e.preventDefault())
  shadow().appendChild(el)
  return el
}

export function button(label: string, onClick: () => void, title = ""): HTMLButtonElement {
  const b = document.createElement("button")
  b.textContent = label
  if (title) b.title = title
  b.addEventListener("click", (e) => {
    e.stopPropagation()
    onClick()
  })
  return b
}

export function toast(text: string, error = false, ms = 4500) {
  const el = document.createElement("div")
  el.className = error ? "toast error" : "toast"
  el.textContent = text
  shadow().appendChild(el)
  setTimeout(() => el.remove(), ms)
}
