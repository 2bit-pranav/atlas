import { type LucideIcon } from "lucide-react"

export function Empty({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <div className="mt-3 flex flex-col items-center rounded-xl border border-dashed px-6 py-10 text-center">
      <Icon className="h-6 w-6 text-muted-foreground" />
      <p className="mt-2 text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{text}</p>
    </div>
  )
}
