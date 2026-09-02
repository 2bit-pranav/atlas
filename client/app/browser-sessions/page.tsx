"use client";

import AppLayout from "@/components/layout/app-layout";
import { X } from "lucide-react";
import { useEffect, useState } from "react";

interface BrowserSession {
    chat_id: string;
    running: boolean;
    persistent: boolean;
}

const API = "http://localhost:8001/api/browser";

export default function BrowserSessionsPage() {
    const [sessions, setSessions] = useState<BrowserSession[]>([]);

    async function load() {
        const response = await fetch(`${API}/sessions`);
        if (response.ok) setSessions((await response.json()).sessions || []);
    }

    useEffect(() => {
        const initial = window.setTimeout(() => void load(), 0);
        const timer = window.setInterval(() => void load(), 1500);
        return () => {
            window.clearTimeout(initial);
            window.clearInterval(timer);
        };
    }, []);

    async function close(chatId: string) {
        await fetch(`${API}/sessions/${chatId}`, { method: "DELETE" });
        await load();
    }

    return (
        <AppLayout>
            <section className="mx-auto h-full w-full max-w-5xl overflow-y-auto p-8">
                <h1 className="text-2xl font-semibold">Browser Sessions</h1>
                <p className="mt-2 text-sm opacity-70">External browser sessions remain open until you close them here.</p>
                <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {sessions.length === 0 && <p className="text-sm opacity-60">No active browser sessions.</p>}
                    {sessions.map((session) => (
                        <article key={session.chat_id} className="rounded-xl border p-4" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                            <div className="flex items-center justify-between gap-3"><strong className="truncate">Chat {session.chat_id}</strong><span className="text-xs opacity-60">{session.running ? "Running" : "Idle"}</span></div>
                            <p className="mt-3 text-xs opacity-60">External headed browser is {session.persistent ? "open" : "starting"}.</p>
                            <div className="mt-4 flex justify-end"><button type="button" onClick={() => void close(session.chat_id)} title="Close browser" aria-label="Close browser" className="rounded-lg border p-2 text-red-400 hover:bg-[var(--surface-hover)]"><X size={14} /></button></div>
                        </article>
                    ))}
                </div>
            </section>
        </AppLayout>
    );
}
