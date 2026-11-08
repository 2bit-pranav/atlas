import { createContext } from "react"

/** True inside the web app's task layout: answers leave tools, approvals and files to the work panel (wide screens). */
export const TaskLayout = createContext(false)

/** True inside the browser extension's side panel: compact answers that point at the page, no stats. */
export const PanelLayout = createContext(false)
