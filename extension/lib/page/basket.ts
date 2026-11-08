/**
 * Dropping a basket card on the page. The card's drag carries only a marker
 * (its basket id); here, a drop carrying it is taken over: the file is read
 * from the local Atlas (through the background worker, which holds the
 * pairing token) and handed to what it was dropped on, as a desktop drag
 * would: an upload field gets it as its file, a drop zone gets a file drop.
 *
 * Only a real drop by the user counts: a page script can fake a drop with
 * the marker in it, and the browser marks that one untrusted. Nothing is drawn
 * while a card is dragged: an outline of ours would claim a spot takes the file
 * when the page may not (Google Forms' "Add file" button opens a picker and
 * ignores drops). The page's own drop styling, if it has any, is the signal.
 *
 * Proven in Edge before it was built (scratchpad spike, 2026-11-08): the drag
 * carries the marker out of the extension page; a plain upload field and a
 * react-dropzone-style zone both received the real file; a faked drop was refused.
 */

export const BASKET_MIME = "application/x-atlas-file"

const ours = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes(BASKET_MIME)

/** The upload field a drop on `el` means: the field itself, its label's field, or the only one in its box. */
export function uploadField(el: Element | null): HTMLInputElement | null {
  if (!el) return null
  const field = el.closest<HTMLInputElement>('input[type="file"]')
  if (field) return field
  const label = el.closest("label") as HTMLLabelElement | null
  if (label?.control?.matches('input[type="file"]')) return label.control as HTMLInputElement
  // Up a few boxes, never to the whole page: a drop zone with no field of its own must not
  // land in some other upload field on the page (it gets the drop instead).
  for (let box: Element | null = el, depth = 0; box && depth < 4 && box !== document.body && box !== document.documentElement;
       box = box.parentElement, depth++) {
    const inside = box.querySelectorAll<HTMLInputElement>('input[type="file"]')
    if (inside.length === 1) return inside[0]
    if (inside.length > 1) return null
  }
  return null
}

export function basketDrops(onStatus: (text: string, failed?: boolean) => void, off: () => boolean) {
  const hover = (e: DragEvent) => {
    if (!ours(e) || off()) return
    e.preventDefault()                                     // lets the drop happen here
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy"
  }
  document.addEventListener("dragenter", hover, true)
  document.addEventListener("dragover", hover, true)

  document.addEventListener("drop", async (e) => {
    if (!ours(e) || off()) return
    e.preventDefault()
    e.stopPropagation()
    if (!e.isTrusted) return                               // made by a page script, not the user
    const id = e.dataTransfer?.getData(BASKET_MIME) ?? ""
    const under = document.elementFromPoint(e.clientX, e.clientY) ?? (e.target as Element)
    const got = await browser.runtime.sendMessage({ type: "atlas:basketFile", id }) as
      { name?: string; type?: string; b64?: string; error?: string }
    if (got?.error || !got?.b64) return onStatus(`Could not add the file: ${got?.error ?? "no answer from Atlas"}`, true)
    const bytes = Uint8Array.from(atob(got.b64), (c) => c.charCodeAt(0))
    const file = new File([bytes], got.name ?? "file", { type: got.type })
    const dt = new DataTransfer()
    dt.items.add(file)
    const field = uploadField(under)
    if (field) {
      if (field.accept && !accepts(field.accept, file)) return onStatus(`This field takes ${field.accept}, not ${file.name}.`, true)
      field.files = dt.files
      field.dispatchEvent(new Event("input", { bubbles: true }))
      field.dispatchEvent(new Event("change", { bubbles: true }))
      return onStatus(`Added ${file.name}. Check it, then submit the form yourself.`)
    }
    // A drop zone: the drop replayed with the file in it.
    for (const type of ["dragenter", "dragover", "drop"])
      under.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt, clientX: e.clientX, clientY: e.clientY }))
    onStatus(`Dropped ${file.name} here. If the page did not take it, open the page's own file picker and drop it in there.`)
  }, true)
}

/** Whether `file` fits an `accept` list (".pdf,image/*"). */
export function accepts(accept: string, file: { name: string; type: string }): boolean {
  return accept.split(",").map((a) => a.trim().toLowerCase()).filter(Boolean).some((a) =>
    a.startsWith(".") ? file.name.toLowerCase().endsWith(a)
      : a.endsWith("/*") ? file.type.toLowerCase().startsWith(a.slice(0, -1))
      : file.type.toLowerCase() === a)
}
