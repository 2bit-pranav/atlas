/** A message in the middle of the panel. */


export function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-dvh items-center justify-center p-6 text-center text-sm text-muted-foreground">{children}</div>
}
