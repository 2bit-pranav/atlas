import { ShieldAlert } from "lucide-react"

/** A guardrail's note for the user: a source spoke to the assistant, or figures had no source. */
export function Notice({ text }: { text: string }) {
  return (
    <p role="note" className="my-2 flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-[13px] leading-5 text-foreground">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
      <span>{text}</span>
    </p>
  )
}
