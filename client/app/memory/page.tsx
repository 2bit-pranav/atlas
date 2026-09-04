"use client";

import AppLayout from "@/components/layout/app-layout";
import { Brain, Plus, Trash2, Edit2, Check, X, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

interface MemoryFact {
    id: string;
    text: string;
    category: string;
    created_at: string;
}

const DEFAULT_FACTS: MemoryFact[] = [
    {
        id: "fact-1",
        text: "User prefers train travel over flights for domestic trips",
        category: "Preferences",
        created_at: "2026-09-01",
    },
    {
        id: "fact-2",
        text: "Target budget range for hardware/laptop recommendations is under ",
        category: "Budget",
        created_at: "2026-09-02",
    },
    {
        id: "fact-3",
        text: "Default UI color theme preference is Dark Mode",
        category: "UI Settings",
        created_at: "2026-09-03",
    },
];

const API = "/api/memory";

export default function MemoryPage() {
    const [facts, setFacts] = useState<MemoryFact[]>(DEFAULT_FACTS);
    const [newFact, setNewFact] = useState("");
    const [newCategory, setNewCategory] = useState("Preferences");
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editText, setEditText] = useState("");
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        async function fetchMemory() {
            try {
                const res = await fetch(API);
                if (res.ok) {
                    const data = await res.json();
                    if (Array.isArray(data.facts)) {
                        setFacts(data.facts);
                    }
                }
            } catch (err) {
                console.error("Failed to load memory.json:", err);
            }
        }
        void fetchMemory();
    }, []);

    async function persistMemory(updated: MemoryFact[]) {
        setFacts(updated);
        setLoading(true);
        try {
            await fetch(API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ facts: updated }),
            });
        } catch (err) {
            console.error("Failed to save memory.json:", err);
        } finally {
            setLoading(false);
        }
    }

    function addFact() {
        if (!newFact.trim()) return;
        const item: MemoryFact = {
            id: "fact-" + Date.now(),
            text: newFact.trim(),
            category: newCategory,
            created_at: new Date().toISOString().split("T")[0],
        };
        void persistMemory([item, ...facts]);
        setNewFact("");
    }

    function deleteFact(id: string) {
        void persistMemory(facts.filter((f) => f.id !== id));
    }

    function startEdit(fact: MemoryFact) {
        setEditingId(fact.id);
        setEditText(fact.text);
    }

    function confirmEdit(id: string) {
        if (!editText.trim()) return;
        void persistMemory(
            facts.map((f) => (f.id === id ? { ...f, text: editText.trim() } : f))
        );
        setEditingId(null);
    }

    return (
        <AppLayout>
            <div className="mx-auto h-full w-full max-w-5xl overflow-y-auto p-8">
                <header className="border-b pb-4" style={{ borderColor: "var(--border)" }}>
                    <h1 className="text-xl font-semibold flex items-center gap-2">
                        <Brain className="h-5 w-5 opacity-80" />
                        Agent Memory Storage
                    </h1>
                    <p className="mt-1 text-xs opacity-70">
                        Manage persistent facts, explicit preferences, and domain guidelines remembered by Atlas.
                    </p>
                </header>

                <div className="mt-6 rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                    <h2 className="text-xs font-medium flex items-center gap-2 mb-3">
                        <Sparkles size={14} className="opacity-70" />
                        Add New Memory Fact
                    </h2>
                    <div className="flex flex-col sm:flex-row gap-2.5">
                        <input
                            type="text"
                            value={newFact}
                            onChange={(e) => setNewFact(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") addFact(); }}
                            placeholder="e.g. User prefers vegetarian restaurants or strictly budget hotels..."
                            className="h-9 min-w-0 flex-1 rounded-lg border bg-transparent px-3 text-xs outline-none"
                            style={{ borderColor: "var(--border)" }}
                        />
                        <select
                            value={newCategory}
                            onChange={(e) => setNewCategory(e.target.value)}
                            className="h-9 rounded-lg border bg-[var(--surface)] px-2.5 text-xs outline-none"
                            style={{ borderColor: "var(--border)" }}
                        >
                            <option value="Preferences">Preferences</option>
                            <option value="Budget">Budget</option>
                            <option value="UI Settings">UI Settings</option>
                            <option value="Travel">Travel</option>
                            <option value="General">General</option>
                        </select>
                        <button
                            type="button"
                            onClick={addFact}
                            disabled={!newFact.trim() || loading}
                            className="flex h-9 items-center justify-center gap-1.5 rounded-lg px-4 text-xs font-medium disabled:opacity-40"
                            style={{ background: "var(--text)", color: "var(--background)" }}
                        >
                            <Plus size={14} />
                            Add Fact
                        </button>
                    </div>
                </div>

                <div className="mt-6 space-y-2.5 pb-12">
                    <h2 className="text-xs font-medium opacity-80 mb-3">Stored Memory Facts ({facts.length})</h2>
                    {facts.length === 0 && (
                        <p className="text-xs opacity-60 italic py-6 text-center">No memory facts stored in memory.json yet.</p>
                    )}
                    {facts.map((fact) => (
                        <div
                            key={fact.id}
                            className="group flex flex-col sm:flex-row items-start sm:items-center justify-between rounded-lg border p-3.5 transition-colors hover:border-white/20"
                            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                        >
                            <div className="flex-1 min-w-0 pr-4">
                                <div className="flex items-center gap-2 mb-1">
                                    <span className="rounded-full px-2 py-0.5 text-[10px] uppercase font-mono tracking-wider border opacity-70" style={{ borderColor: "var(--border)" }}>
                                        {fact.category}
                                    </span>
                                    <span className="text-[10px] opacity-40 font-mono">Saved {fact.created_at}</span>
                                </div>
                                {editingId === fact.id ? (
                                    <div className="mt-2 flex items-center gap-2">
                                        <input
                                            type="text"
                                            value={editText}
                                            onChange={(e) => setEditText(e.target.value)}
                                            className="h-9 flex-1 rounded-lg border bg-transparent px-3 text-xs outline-none"
                                            style={{ borderColor: "var(--border)" }}
                                            autoFocus
                                        />
                                        <button
                                            type="button"
                                            onClick={() => confirmEdit(fact.id)}
                                            className="p-2 rounded-lg bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30"
                                            title="Save edit"
                                        >
                                            <Check size={14} />
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setEditingId(null)}
                                            className="p-2 rounded-lg hover:bg-[var(--surface-hover)] opacity-70"
                                            title="Cancel edit"
                                        >
                                            <X size={14} />
                                        </button>
                                    </div>
                                ) : (
                                    <p className="text-xs font-medium leading-relaxed opacity-90">{fact.text}</p>
                                )}
                            </div>

                            {editingId !== fact.id && (
                                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity mt-2 sm:mt-0">
                                    <button
                                        type="button"
                                        onClick={() => startEdit(fact)}
                                        className="p-1.5 rounded-lg hover:bg-[var(--surface-hover)] opacity-70 hover:opacity-100"
                                        title="Edit fact"
                                    >
                                        <Edit2 size={14} />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => deleteFact(fact.id)}
                                        className="p-1.5 rounded-lg hover:bg-[var(--surface-hover)] text-red-400 opacity-70 hover:opacity-100"
                                        title="Delete fact"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </AppLayout>
    );
}