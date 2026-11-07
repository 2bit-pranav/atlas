import { Download } from "lucide-react"
import type { ChangedFile } from "@/api/types"
import { FileLink } from "@/features/chat/FileLink"
import { Tip } from "@/components/ui/tip"
import { formatBytes } from "@/lib/format"

/** Files this answer created or changed, to download. */
export function ProducedFiles({ files, chatId }: { files: ChangedFile[]; chatId: string }) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {files.map((f) => {
        const ext = f.name.includes(".") ? f.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
        return (
          <div key={f.name} className="flex items-center gap-3 rounded-lg border bg-muted p-2 pr-1.5">
            <span className="flex h-8 w-8 items-center justify-center rounded bg-primary/10 text-[10px] font-semibold text-primary">{ext}</span>
            <span className="min-w-0">
              <span className="block max-w-48 truncate text-sm font-medium" title={f.name}>{f.name}</span>
              <span className="block text-xs text-muted-foreground">{f.change === "created" ? "Created" : "Updated"} · {formatBytes(f.size)}</span>
            </span>
            <Tip label="Download">
              <FileLink chatId={chatId} name={f.name} download
                        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground">
                <Download className="h-3.5 w-3.5" />
              </FileLink>
            </Tip>
          </div>
        )
      })}
    </div>
  )
}
