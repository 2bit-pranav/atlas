import { cn } from "@/lib/cn"

export function SectionHead({ title, text }: { title: string; text: string }) {
  return (
    <div className="mb-2 mt-2">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{text}</p>
    </div>
  )
}

export function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="divide-y rounded-xl border bg-card">{children}</div>
    </section>
  )
}

export function Row({ label, help, children, badge, wide }: {
  label: string; help?: string; children: React.ReactNode; badge?: React.ReactNode; wide?: boolean
}) {
  return (
    <div className={cn("flex gap-4 px-4 py-3", wide ? "flex-col" : "items-center")}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-medium">{label}{badge}</div>
        {help && <p className="mt-0.5 text-xs text-muted-foreground">{help}</p>}
      </div>
      <div className={cn(wide ? "w-full" : "shrink-0")}>{children}</div>
    </div>
  )
}
