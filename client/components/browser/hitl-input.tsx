"use client";

import { useState } from "react";
import { Send } from "lucide-react";
import { useChatStore } from "@/stores/chat-store";

export default function HitlInput() {
    const handoff = useChatStore((state) => state.browserHandoff);
    const resolve = useChatStore((state) => state.resolveBrowserHandoff);
    const [response, setResponse] = useState("");
    const [error, setError] = useState<string | null>(null);

    if (!handoff) return null;

    async function submit() {
        if (!response.trim()) return;
        setError(null);
        try {
            await resolve(response);
            setResponse("");
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : "Could not resume browser task.");
        }
    }

    return (
        <section className="mx-auto mb-3 w-full max-w-4xl rounded-xl border p-3" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
            <p className="mb-2 text-sm">{handoff.question}</p>
            <div className="flex gap-2">
                <input value={response} onChange={(event) => setResponse(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void submit(); }} className="h-9 min-w-0 flex-1 rounded-lg border bg-transparent px-3 text-sm" placeholder="Type your response" autoComplete="off" />
                <button type="button" onClick={() => void submit()} disabled={!response.trim()} title="Send response" aria-label="Send response" className="flex h-9 w-9 items-center justify-center rounded-lg disabled:opacity-40" style={{ background: "var(--text)", color: "var(--background)" }}><Send size={15} /></button>
            </div>
            {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        </section>
    );
}
