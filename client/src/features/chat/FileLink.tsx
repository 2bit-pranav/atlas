/**
 * Links to and images of a chat's files. In the web UI they are plain URLs.
 * In the extension the backend wants the pairing token, which must never be
 * in a URL (history, logs, Referer), so the file is fetched with it in a
 * header and shown from a local blob.
 */

import { useEffect, useState, type ReactNode } from "react"

import { fetchFile, fileUrl, needsToken } from "@/api/client"

export function FileLink({ chatId, name, download = false, className, title, children }: {
  chatId: string; name: string; download?: boolean; className?: string; title?: string; children: ReactNode
}) {
  if (!needsToken())
    return download
      ? <a href={fileUrl(chatId, name, true)} className={className} title={title}>{children}</a>
      : <a href={fileUrl(chatId, name)} target="_blank" rel="noreferrer" className={className} title={title}>{children}</a>
  const open = async () => {
    const url = URL.createObjectURL(await fetchFile(chatId, name))
    if (download) {
      const a = document.createElement("a")
      a.href = url
      a.download = name.split("/").pop() ?? name
      a.click()
    } else {
      window.open(url, "_blank", "noopener")
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  return (
    <a href="#" className={className} title={title}
       onClick={(e) => { e.preventDefault(); void open().catch(() => undefined) }}>
      {children}
    </a>
  )
}

export function FileImage({ chatId, name, className }: { chatId: string; name: string; className?: string }) {
  const [src, setSrc] = useState(() => (needsToken() ? "" : fileUrl(chatId, name)))
  useEffect(() => {
    if (!needsToken()) return
    let url = ""
    let live = true
    void fetchFile(chatId, name).then((blob) => {
      url = URL.createObjectURL(blob)
      if (live) setSrc(url)
      else URL.revokeObjectURL(url)
    }).catch(() => undefined)
    return () => {
      live = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [chatId, name])
  return src ? <img src={src} alt={name} className={className} /> : <span className={className} />
}
