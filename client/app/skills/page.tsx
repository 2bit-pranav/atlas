"use client";

import AppLayout from "@/components/layout/app-layout";
import { RefreshCw, Trash2, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

interface Skill {
    name: string;
    description?: string;
}

const API = "http://localhost:8001/api/skills";

export default function SkillsPage() {
    const [installed, setInstalled] = useState<Skill[]>([]);
    const [command, setCommand] = useState("");
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);

    async function loadInstalled() {
        const response = await fetch(`${API}/local`);
        if (response.ok) setInstalled((await response.json()).skills || []);
    }

    useEffect(() => {
        const timer = window.setTimeout(() => void loadInstalled(), 0);
        return () => window.clearTimeout(timer);
    }, []);

    async function install() {
        if (!command.trim()) return;
        setBusy(true);
        setMessage("Installing skill...");
        try {
            const response = await fetch(`${API}/install`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ command }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || "Installation failed.");
            setCommand("");
            setMessage(`${data.skills?.join(", ") || "Skill"} installed successfully.`);
            await loadInstalled();
        } catch (error) {
            setMessage(error instanceof Error ? error.message : "Installation failed.");
        } finally {
            setBusy(false);
        }
    }

    async function remove(name: string) {
        setBusy(true);
        const response = await fetch(`${API}/${encodeURIComponent(name)}`, { method: "DELETE" });
        setMessage(response.ok ? `${name} removed from Atlas.` : "Could not remove the skill.");
        if (response.ok) await loadInstalled();
        setBusy(false);
    }

    async function updateAll() {
        setBusy(true);
        setMessage("Updating installed skills...");
        const response = await fetch(`${API}/update-all`, { method: "POST" });
        const data = await response.json().catch(() => ({}));
        setMessage(response.ok ? `${data.skills?.length || 0} skill(s) updated.` : (data.detail || "Update failed."));
        if (response.ok) await loadInstalled();
        setBusy(false);
    }

    return (
        <AppLayout>
            <section className="mx-auto h-full w-full max-w-5xl overflow-y-auto p-8">
                <header>
                    <h1 className="text-2xl font-semibold">Skills</h1>
                    <p className="mt-2 max-w-2xl text-sm leading-6 opacity-75">
                        Skills are reusable instruction sets that give Atlas additional knowledge and capable tools for specific tasks. Browse the catalog at <a className="underline" href="https://skills.sh" target="_blank" rel="noreferrer">skills.sh</a>, then paste its install command below. Atlas will automatically install it, so it becomes available to this workspace.
                    </p>
                </header>

                <div className="mt-6 rounded-xl border p-5" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                    <h2 className="font-medium">Install from skills.sh</h2>
                    <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm opacity-75">
                        <li>Open skills.sh and find a skill you want to use.</li>
                        <li>Copy the provided <code>npx skills add ...</code> command.</li>
                        <li>Paste it here and run.</li>
                    </ol>
                    <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                        <input value={command} onChange={(event) => setCommand(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void install(); }} placeholder="npx skills add owner/repository --skill skill-name" className="h-10 min-w-0 flex-1 rounded-lg border bg-transparent px-3 text-sm" disabled={busy} />
                        <button type="button" onClick={() => void install()} disabled={!command.trim() || busy} className="h-10 rounded-lg px-4 text-sm font-medium disabled:opacity-40" style={{ background: "var(--text)", color: "var(--background)" }}>Install</button>
                    </div>
                    {message && <p className="mt-3 text-sm opacity-75">{message}</p>}
                </div>

                <div className="mt-10 flex items-center justify-between gap-4">
                    <div><h2 className="text-lg font-medium">Manage installed skills</h2><p className="mt-1 text-sm opacity-65">Installed skills are preloaded into Atlas automatically.</p></div>
                    <button type="button" onClick={() => void updateAll()} disabled={busy || installed.length === 0} title="Update all installed skills" aria-label="Update all installed skills" className="flex h-9 items-center gap-2 rounded-lg border px-3 text-sm disabled:opacity-40"><RefreshCw size={15} />Update all</button>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {installed.length === 0 && <p className="text-sm opacity-60">No skills installed yet.</p>}
                    {installed.map((skill) => (
                        <article key={skill.name} className="group relative min-h-32 rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                            <div className="flex items-start gap-2 pr-16"><Wrench size={16} className="mt-0.5 shrink-0 opacity-60" /><strong className="truncate">{skill.name}</strong></div>
                            <p className="mt-3 line-clamp-3 text-sm opacity-70">{skill.description || "Installed Atlas skill"}</p>
                            <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                                <button type="button" onClick={() => void updateAll()} title="Update all installed skills" aria-label="Update all installed skills" className="rounded p-1.5 hover:bg-[var(--surface-hover)]"><RefreshCw size={14} /></button>
                                <button type="button" onClick={() => void remove(skill.name)} title={`Delete ${skill.name}`} aria-label={`Delete ${skill.name}`} className="rounded p-1.5 text-red-400 hover:bg-[var(--surface-hover)]"><Trash2 size={14} /></button>
                            </div>
                        </article>
                    ))}
                </div>
            </section>
        </AppLayout>
    );
}
