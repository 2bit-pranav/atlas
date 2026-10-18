import type { ReactNode } from "react"
import * as Tooltip from "@radix-ui/react-tooltip"

/** A one-line tooltip. The app is wrapped in a single `Tooltip.Provider`. */
export function Tip({ label, children, side = "top" }: {
  label: ReactNode
  children: ReactNode
  side?: "top" | "right" | "bottom" | "left"
}) {
  return (
    <Tooltip.Root delayDuration={300}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side={side} sideOffset={6}
                         className="z-50 rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground shadow-md">
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}
