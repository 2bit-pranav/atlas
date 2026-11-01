import * as Dialog from "@radix-ui/react-dialog"
import type { ChatSummary } from "@/api/types"
import { Button } from "@/components/ui/Button"

export function DeleteDialog({ chat, onClose, onConfirm }: {
  chat: ChatSummary | null
  onClose: () => void
  onConfirm: (chat: ChatSummary) => void
}) {
  return (
    <Dialog.Root open={chat !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-background p-5 shadow-lg">
          <Dialog.Title className="text-base font-semibold">Delete conversation</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-muted-foreground">
            "{chat?.title || "New chat"}" will be deleted, with every version, its model history and its uploaded files.
            This cannot be undone.
          </Dialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="destructive" onClick={() => chat && onConfirm(chat)} autoFocus>Delete</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
