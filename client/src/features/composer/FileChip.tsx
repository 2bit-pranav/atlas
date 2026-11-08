import { Loader2, X } from "lucide-react"
import type { ChatFile, IngestStatus } from "@/api/types"
import { formatBytes } from "@/lib/format"

/** What parsing has got to, in a few words; nothing once it is ready. */
function progress(ingest: IngestStatus | undefined): string | null {
  if (!ingest || ingest.status === "ready") return null
  if (ingest.status === "failed") return "Couldn't read"
  if (ingest.status === "reading" && ingest.total > 1) return `Reading ${ingest.done}/${ingest.total} pages`
  return "Reading…"
}

export function FileChip({ file, uploading, ingest, onRemove }: {
  file: ChatFile; uploading: boolean; ingest?: IngestStatus; onRemove: () => void
}) {
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
  const note = progress(ingest)
  return (
    <div className="group relative flex shrink-0 items-center gap-3 rounded-lg border bg-muted p-2.5 pr-7">
      <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">
        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : ext}
      </span>
      <span className="min-w-0">
        <span className="block max-w-32 truncate text-sm font-medium">{file.name}</span>
        <span className="block text-xs text-muted-foreground" aria-live="polite">
          {formatBytes(file.size)}{note && <> · <span className={ingest?.status === "failed" ? "text-destructive" : ""}>{note}</span></>}
        </span>
      </span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${file.name}`}
              className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground opacity-100 hover:bg-background hover:text-foreground md:opacity-0 md:group-hover:opacity-100">
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}
