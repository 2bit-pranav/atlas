import React from "react"
import { CheckCircle2, X, XCircle } from "lucide-react"
import { cn } from "@/lib/cn"

export function Notice({ tone, children, onClose }: {
  tone: "error" | "success" | "info"
  children: React.ReactNode
  onClose?: () => void
}) {
  const Icon = tone === "error" ? XCircle : CheckCircle2
  return (
    <div className={cn(
      "mt-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
      tone === "error" && "border-destructive/30 bg-destructive/10 text-destructive",
      tone === "success" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
      tone === "info" && "bg-muted/50 text-muted-foreground",
    )}>
      <Icon className="mt-px h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{children}</span>
      {onClose && (
        <button type="button" onClick={onClose} className="opacity-60 hover:opacity-100" aria-label="Dismiss">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}
