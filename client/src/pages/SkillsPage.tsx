/**
 * Skills: what the agent can load, and where new ones come from.
 *
 * Install accepts exactly what skills.sh shows on a skill's page -- the
 * `npx skills add ...` line -- or a GitHub URL, or a zip. Nothing is run: the
 * backend reads the command for the repository and skill name and fetches the
 * folder itself.
 */

import { useEffect, useRef, useState } from "react"
import { AlertTriangle, Download, FolderOpen, Loader2, Package, Trash2, Upload } from "lucide-react"

import * as api from "@/lib/api"
import type { Skill, SkillInstallResult } from "@/lib/types"
import { PageShell, Switch, Button, Notice, Empty } from "@/components/ui/kit"
import { cn } from "@/lib/utils"

export function SkillsPage() {
  const [skills, setSkills] = useState<Skill[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const run = async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setError(null)
    try {
      return await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }

  useEffect(() => {
    void run(api.listSkills).then((s) => s && setSkills(s))
  }, [])

  const enabledCount = (skills ?? []).filter((s) => s.enabled).length

  return (
    <PageShell
      title="Skills"
      description="Folders with a SKILL.md. The model sees each skill's name and description, and loads the full instructions only when it decides one applies."
    >
      <InstallCard
        onInstalled={(result) => {
          setSkills(result.skills)
          if (result.installed.length)
            setNotice(`Installed ${result.installed.map((s) => s.name).join(", ")}.`)
        }}
        run={run}
      />

      {error && <Notice tone="error">{error}</Notice>}
      {notice && <Notice tone="success" onClose={() => setNotice(null)}>{notice}</Notice>}

      <div className="mt-8 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">Installed</h2>
        {skills && (
          <span className="text-xs text-muted-foreground">
            {enabledCount} of {skills.length} on
          </span>
        )}
      </div>

      {skills === null ? (
        <div className="mt-6 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : skills.length === 0 ? (
        <Empty icon={Package} title="No skills yet" text="Paste an install command from skills.sh above." />
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {skills.map((skill) => (
            <SkillCard
              key={skill.folder}
              skill={skill}
              onToggle={async (enabled) => {
                const next = await run(() => api.toggleSkill(skill.folder, enabled))
                if (next) setSkills(next)
              }}
              onDelete={async () => {
                const next = await run(() => api.deleteSkill(skill.folder))
                if (next) setSkills(next)
              }}
              onRequirements={async () => {
                const out = await run(() => api.installRequirements(skill.folder))
                if (out) setNotice(out.ok ? `Installed what ${skill.name} needs.`
                                          : `Install failed:\n${out.output}`)
                const next = await run(api.listSkills)
                if (next) setSkills(next)
              }}
            />
          ))}
        </div>
      )}
    </PageShell>
  )
}

function InstallCard({ onInstalled, run }: {
  onInstalled: (r: SkillInstallResult) => void
  run: <T>(fn: () => Promise<T>) => Promise<T | null>
}) {
  const [command, setCommand] = useState("")
  const [busy, setBusy] = useState(false)
  const [choices, setChoices] = useState<SkillInstallResult["choices"]>([])
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const file = useRef<HTMLInputElement>(null)

  const install = async (choose?: string[]) => {
    setBusy(true)
    const result = await run(() => api.installSkill(command, choose))
    setBusy(false)
    if (!result) return
    if (result.choices.length) {
      setChoices(result.choices)
      setPicked(new Set())
      return
    }
    setChoices([])
    setCommand("")
    onInstalled(result)
  }

  return (
    <div className="rounded-xl border bg-card p-4">
      <label className="text-sm font-medium" htmlFor="skill-cmd">Install a skill</label>
      <p className="mt-1 text-xs text-muted-foreground">
        Open a skill on <span className="font-mono">skills.sh</span>, copy its install command and paste it here. A GitHub URL or
        <span className="font-mono"> owner/repo</span> works too.
      </p>
      <div className="mt-3 flex gap-2">
        <input
          id="skill-cmd"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && command.trim() && !busy && void install()}
          placeholder="npx skills add https://github.com/anthropics/skills --skill pdf"
          className="h-9 min-w-0 flex-1 rounded-lg border bg-background px-3 font-mono text-xs outline-none focus:ring-2 focus:ring-ring/30"
        />
        <Button onClick={() => void install()} disabled={!command.trim() || busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Install
        </Button>
        <Button variant="outline" onClick={() => file.current?.click()} disabled={busy} title="Upload a zip">
          <Upload className="h-4 w-4" />
          Zip
        </Button>
        <input
          ref={file}
          type="file"
          accept=".zip"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0]
            e.target.value = ""
            if (!f) return
            setBusy(true)
            const result = await run(() => api.uploadSkill(f))
            setBusy(false)
            if (result) onInstalled(result)
          }}
        />
      </div>

      {choices.length > 0 && (
        <div className="mt-4 rounded-lg border bg-muted/30 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium">This repository has {choices.length} skills. Pick the ones to install.</span>
            <Button size="sm" disabled={!picked.size || busy} onClick={() => void install([...picked])}>
              Install {picked.size || ""}
            </Button>
          </div>
          <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
            {choices.map((c) => (
              <label key={c.folder} className="flex cursor-pointer gap-2 rounded-md px-2 py-1.5 hover:bg-background">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={picked.has(c.folder)}
                  onChange={(e) => {
                    const next = new Set(picked)
                    if (e.target.checked) next.add(c.folder)
                    else next.delete(c.folder)
                    setPicked(next)
                  }}
                />
                <span className="min-w-0">
                  <span className="block text-xs font-medium">{c.name}</span>
                  <span className="line-clamp-2 block text-xs text-muted-foreground">{c.description}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SkillCard({ skill, onToggle, onDelete, onRequirements }: {
  skill: Skill
  onToggle: (enabled: boolean) => void
  onDelete: () => void
  onRequirements: () => void
}) {
  const [confirm, setConfirm] = useState(false)
  const heavy = skill.tokens > 2500
  const missing = skill.requirements.filter((r) => !r.installed).length
  return (
    <div className={cn("flex flex-col rounded-xl border bg-card p-4", !skill.enabled && "opacity-70")}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold">{skill.name}</span>
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              {skill.bundled ? "bundled" : "installed"}
            </span>
          </div>
          <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{skill.error ?? skill.description}</p>
        </div>
        <Switch checked={skill.enabled} disabled={Boolean(skill.error)} onChange={onToggle} label={`Enable ${skill.name}`} />
      </div>

      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className={cn(heavy && "text-amber-600 dark:text-amber-400")} title="Tokens added to the context when the model loads this skill">
          ~{skill.tokens.toLocaleString()} tokens when loaded
        </span>
        <span>{skill.scripts.length ? `${skill.scripts.length} script${skill.scripts.length > 1 ? "s" : ""}` : "no scripts"}</span>
        {skill.origin?.source && <span className="truncate font-mono" title={skill.origin.command ?? skill.origin.source}>{skill.origin.source}</span>}
      </div>

      {(heavy || skill.requirements.length > 0) && (
        <div className="mt-3 space-y-2 rounded-lg bg-muted/40 p-2.5 text-[11px]">
          {heavy && (
            <p className="flex gap-1.5 text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
              Long instructions. A small model may follow them poorly, and they take a large share of a 32k window.
            </p>
          )}
          {skill.requirements.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex flex-wrap gap-1">
                {skill.requirements.map((r) => (
                  <span key={r.manager + r.package}
                        title={`${r.manager}${r.scope === "global" ? " (global)" : ""}: ${r.installed ? "installed" : "missing"}`}
                        className={cn("rounded px-1.5 py-0.5 font-mono",
                                      r.installed ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                                                  : "bg-amber-500/15 text-amber-700 dark:text-amber-400")}>
                    {r.installed ? "✓" : "✗"} {r.package}
                  </span>
                ))}
              </div>
              {missing > 0 && (
                <div className="flex items-center justify-between gap-2">
                  <span className="text-muted-foreground">{missing} missing: its scripts may fail.</span>
                  <Button size="sm" variant="outline" onClick={onRequirements}>Install {missing}</Button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-auto flex items-center justify-end gap-1 pt-3">
        <span className="mr-auto flex items-center gap-1 truncate text-[11px] text-muted-foreground" title={skill.path}>
          <FolderOpen className="h-3 w-3 shrink-0" />
          <span className="truncate font-mono">skills/{skill.folder}</span>
        </span>
        {!skill.bundled && (confirm ? (
          <>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
            <Button size="sm" variant="destructive" onClick={onDelete}>Delete</Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirm(true)} title="Delete this skill">
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        ))}
      </div>
    </div>
  )
}
