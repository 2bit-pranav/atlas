/** Fill suggestions: the form's fields out, previewed values back, and files for its upload fields. */

import * as api from "@/api/client"
import { tabCall, type TabInfo } from "@ext/shared/tab"

// --------------------------------------------------------------------- fill --

/** What Fill shows in the panel while it works and when it is done: an action's result, not a chat turn. */
export type FillNote = { state: "working" | "done" | "failed"; title: string; lines?: string[] }

/**
 * Fields out, suggestions back, shown on the page. Filling waits for the
 * user's Apply there. Files Atlas found for upload fields go to the basket
 * (`onFiles`): the user drags them onto the page; nothing is uploaded here.
 */
export async function suggestFill(tab: TabInfo, note: (n: FillNote) => void, onFiles?: (cards: api.BasketCard[]) => void) {
  note({ state: "working", title: "Reading the form…" })
  const found = await tabCall(tab.id, "formFields")
  if (found.error) return note({ state: "failed", title: "Could not read the form", lines: [String(found.error)] })
  const fields = (found.fields as { id: string; label: string }[]) ?? []
  if (!fields.length) return note({ state: "failed", title: "No fields to fill on this page",
                                    lines: ["Passwords, codes and card numbers are never filled."] })
  note({ state: "working", title: `Matching ${fields.length} fields to your details and files…` })
  try {
    const { values, missing, files = [] } = await api.suggestFill(fields, String(found.title ?? tab.title))
    if (files.length) onFiles?.(files)
    const shown = Object.keys(values).length ? await tabCall(tab.id, "previewFill", { values }) : { shown: 0 }
    const n = Number(shown.shown ?? 0)
    const plural = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`
    note({
      state: n || files.length ? "done" : "failed",
      title: n ? `${plural(n, "answer")} shown on the form`
        : files.length ? "Nothing to type into this form"
        : "Your details did not answer this form",
      lines: [
        n ? "Check them there, then Apply or Discard on the bar. Nothing is submitted." : "",
        files.length ? `${plural(files.length, "file")} for its uploads in Related files: drag onto the upload question.` : "",
        missing.length ? `Not in your details: ${missing.slice(0, 8).join(", ")}${missing.length > 8 ? "…" : ""}` : "",
      ].filter(Boolean),
    })
  } catch (error) {
    note({ state: "failed", title: "Fill did not finish", lines: [error instanceof Error ? error.message : String(error)] })
  }
}
