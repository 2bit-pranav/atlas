/** Save JSON as a file the browser downloads. */
export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** `2026-10-18_14-02-11_conv_1a2b3c4d_my-chat.json`, like llama.cpp's export names. */
export function exportName(id: string, title: string) {
  const stamp = new Date().toISOString().slice(0, 19).replace("T", "_").replace(/:/g, "-")
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 20)
  return `${stamp}_conv_${id.slice(0, 8)}${slug ? `_${slug}` : ""}.json`
}
