import React from "react"
import { Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

/** A full page beside the sidebar, with a way back to the chat. */
export function PageShell({ title, description, children, actions }: {
  title: string
  description?: string
  children: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-4xl px-4 pb-16 pt-6 sm:px-8">
        <Link to="/" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to chat
        </Link>
        <div className="mt-3 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {description && <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>}
          </div>
          {actions}
        </div>
        <div className="mt-6">{children}</div>
      </div>
    </div>
  )
}
