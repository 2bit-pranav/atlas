import { cn } from "@/lib/cn"

/** The file's type as a coloured tile: sheets green, documents blue, PDFs red, the rest grey. */
const TONE: Record<string, string> = {
  XLSX: "bg-ok/10 text-ok", XLS: "bg-ok/10 text-ok", CSV: "bg-ok/10 text-ok",
  DOCX: "bg-run/10 text-run", DOC: "bg-run/10 text-run", MD: "bg-run/10 text-run", TXT: "bg-run/10 text-run",
  PDF: "bg-destructive/10 text-destructive",
}

export function FileBadge({ name }: { name: string }) {
  const ext = name.includes(".") ? name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE"
  return (
    <span className={cn("flex h-8.5 w-8.5 shrink-0 items-center justify-center rounded-lg font-mono text-[10px] font-semibold",
                        TONE[ext] ?? "bg-muted text-muted-foreground")}>
      {ext}
    </span>
  )
}
