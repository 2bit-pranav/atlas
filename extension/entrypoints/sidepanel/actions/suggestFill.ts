/** Fill suggestions: the form's fields out, previewed values back. */

import * as api from "@/api/client"
import { tabCall, type TabInfo } from "@ext/shared/tab"

// --------------------------------------------------------------------- fill --

/** Fields out, suggestions back, shown on the page. Filling waits for the user's Apply there. */
export async function suggestFill(tab: TabInfo, status: (s: string) => void) {
  status("Reading the form…")
  const found = await tabCall(tab.id, "formFields")
  if (found.error) return status(String(found.error))
  const fields = (found.fields as { id: string; label: string }[]) ?? []
  if (!fields.length) return status("No fields to fill on this page (passwords, codes and card numbers are never filled).")
  status(`Matching ${fields.length} fields to your details…`)
  try {
    const { values, missing } = await api.suggestFill(fields, String(found.title ?? tab.title))
    const shown = await tabCall(tab.id, "previewFill", { values })
    const n = Number(shown.shown ?? 0)
    status(n
      ? `Suggested ${n} value${n === 1 ? "" : "s"}: check them on the page, then Apply there. Nothing is submitted.` +
        (missing.length ? `\nNot in your details: ${missing.slice(0, 8).join(", ")}${missing.length > 8 ? "…" : ""}` : "")
      : "Your details did not answer any of this form's fields.")
  } catch (error) {
    status(error instanceof Error ? error.message : String(error))
  }
}
