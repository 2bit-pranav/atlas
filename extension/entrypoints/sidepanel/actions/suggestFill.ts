/** Fill suggestions: the form's fields out, previewed values back, and files for its upload fields. */

import * as api from "@/api/client"
import { tabCall, type TabInfo } from "@ext/shared/tab"

// --------------------------------------------------------------------- fill --

/**
 * Fields out, suggestions back, shown on the page. Filling waits for the
 * user's Apply there. Files Atlas found for upload fields go to the basket
 * (`onFiles`): the user drags them onto the page; nothing is uploaded here.
 */
export async function suggestFill(tab: TabInfo, status: (s: string) => void, onFiles?: (cards: api.BasketCard[]) => void) {
  status("Reading the form…")
  const found = await tabCall(tab.id, "formFields")
  if (found.error) return status(String(found.error))
  const fields = (found.fields as { id: string; label: string }[]) ?? []
  if (!fields.length) return status("No fields to fill on this page (passwords, codes and card numbers are never filled).")
  status(`Matching ${fields.length} fields to your details and files…`)
  try {
    const { values, missing, files = [] } = await api.suggestFill(fields, String(found.title ?? tab.title))
    if (files.length) onFiles?.(files)
    const shown = Object.keys(values).length ? await tabCall(tab.id, "previewFill", { values }) : { shown: 0 }
    const n = Number(shown.shown ?? 0)
    const lines = [
      n ? `Suggested ${n} value${n === 1 ? "" : "s"}: check them on the page, then Apply there. Nothing is submitted.`
        : files.length ? "Nothing to type into this form." : "Your details did not answer any of this form's fields.",
      files.length ? `Found ${files.length} file${files.length === 1 ? "" : "s"} for its upload fields: drag them from Related files.` : "",
      missing.length ? `Not found: ${missing.slice(0, 8).join(", ")}${missing.length > 8 ? "…" : ""}` : "",
    ]
    status(lines.filter(Boolean).join("\n"))
  } catch (error) {
    status(error instanceof Error ? error.message : String(error))
  }
}
