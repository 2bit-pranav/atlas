/**
 * The handful of primitives every page uses. Plain Tailwind on the theme
 * tokens in index.css, so restyling the app is a palette change, not a hunt.
 */

import React from "react"
import { Link } from "react-router-dom"
import { ArrowLeft, CheckCircle2, X, XCircle, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

type ButtonVariant = "default" | "outline" | "ghost" | "destructive" | "secondary"
type ButtonSize = "default" | "sm" | "icon" | "icon-sm"

const variants: Record<ButtonVariant, string> = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  outline: "border bg-background hover:bg-accent hover:text-accent-foreground",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
}
const sizes: Record<ButtonSize, string> = {
  default: "h-9 px-3.5 text-sm",
  sm: "h-7 px-2.5 text-xs",
  icon: "h-9 w-9",
  "icon-sm": "h-7 w-7",
}

export const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }
>(function Button({ className, variant = "default", size = "default", type = "button", ...props }, ref) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-50",
        variants[variant], sizes[size], className,
      )}
      {...props}
    />
  )
})

export function Switch({ checked, onChange, disabled, label }: {
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
  label?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary" : "bg-input",
      )}
    >
      <span className={cn("inline-block h-4 w-4 rounded-full bg-background shadow transition-transform",
                          checked ? "translate-x-[18px]" : "translate-x-0.5")} />
    </button>
  )
}

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

export function Empty({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <div className="mt-3 flex flex-col items-center rounded-xl border border-dashed px-6 py-10 text-center">
      <Icon className="h-6 w-6 text-muted-foreground" />
      <p className="mt-2 text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{text}</p>
    </div>
  )
}

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

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border bg-muted px-1 font-mono text-[10px] font-medium text-muted-foreground">
      {children}
    </kbd>
  )
}
