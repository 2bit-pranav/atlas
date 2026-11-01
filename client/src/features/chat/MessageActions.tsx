import { useState } from "react"
import { Check, Copy } from "lucide-react"
import { Tip } from "@/components/ui/tip"

export function Action({ label, onClick, disabled, children }: {
  label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <Tip label={label}>
      <button type="button" onClick={onClick} disabled={disabled} aria-label={label}
              className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:opacity-30">
        {children}
      </button>
    </Tip>
  )
}

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <Action label={done ? "Copied" : "Copy"} onClick={() => {
      void navigator.clipboard.writeText(text)
      setDone(true)
      setTimeout(() => setDone(false), 1200)
    }}>
      {done ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
    </Action>
  )
}
