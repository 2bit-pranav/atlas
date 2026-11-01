import { cn } from "@/lib/cn"

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
