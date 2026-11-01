import { useState } from "react"
import { Download, MessagesSquare, Upload } from "lucide-react"
import { atlas, useAtlas } from "@/state/store"
import { downloadJson } from "@/lib/download"
import { Button } from "@/components/ui/Button"
import { Notice } from "@/components/ui/Notice"
import { Group, Row, SectionHead } from "@/features/settings/layout"

export function ConversationsSection() {
  const chats = useAtlas((s) => s.chats)
  const [message, setMessage] = useState<string | null>(null)
  const [confirm, setConfirm] = useState(false)
  return (
    <div>
      <SectionHead title="Conversations" text="Exports include every version and the model's history, so an imported chat can be continued." />
      <Group title="Import and export">
        <Row label="Export all conversations" help={`${chats.length} conversation(s) as one JSON file.`}>
          <Button variant="outline" disabled={!chats.length} onClick={async () => {
            downloadJson(`atlas-conversations-${new Date().toISOString().slice(0, 10)}.json`,
                         await atlas.exportChats(chats.map((c) => c.id)))
          }}><Download className="h-3.5 w-3.5" />Export</Button>
        </Row>
        <Row label="Import conversations" help="A file exported from Atlas: one conversation or many.">
          <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-3.5 text-sm font-medium hover:bg-accent">
            <Upload className="h-3.5 w-3.5" />Import
            <input type="file" accept="application/json,.json" hidden onChange={async (e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (!file) return
              try {
                const n = await atlas.importChats(JSON.parse(await file.text()))
                setMessage(`Imported ${n} conversation(s).`)
              } catch (err) {
                setMessage(`Import failed: ${err instanceof Error ? err.message : err}`)
              }
            }} />
          </label>
        </Row>
      </Group>
      {message && <Notice tone="info" onClose={() => setMessage(null)}>{message}</Notice>}
      <Group title="Danger zone">
        <Row label="Delete all conversations" help="Removes every chat, its snapshots and its uploaded files.">
          {confirm ? (
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
              <Button variant="destructive" onClick={async () => { await atlas.deleteAllChats(); setConfirm(false) }}>
                Delete {chats.length}
              </Button>
            </div>
          ) : (
            <Button variant="outline" className="text-destructive" disabled={!chats.length} onClick={() => setConfirm(true)}>
              <MessagesSquare className="h-3.5 w-3.5" />Delete all
            </Button>
          )}
        </Row>
      </Group>
    </div>
  )
}
