import React from "react"
import { cn } from "@/lib/cn"

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
