import { Loader2, X } from "lucide-react"
import type { ChatFile } from "@/api/types"
import { formatBytes } from "@/lib/format"

export function FileChip({ file, uploading, onRemove }: { file: ChatFile; uploading: boolean; onRemove: () => void }) {
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
  return (
    <div className="group relative flex shrink-0 items-center gap-3 rounded-lg border bg-muted p-2.5 pr-7">
      <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">
        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : ext}
      </span>
      <span className="min-w-0">
        <span className="block max-w-32 truncate text-sm font-medium">{file.name}</span>
        <span className="block text-xs text-muted-foreground">{formatBytes(file.size)}</span>
      </span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${file.name}`}
              className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground opacity-100 hover:bg-background hover:text-foreground md:opacity-0 md:group-hover:opacity-100">
        <X className="h-3 w-3" />
      </button>
    </div>
  )
}
