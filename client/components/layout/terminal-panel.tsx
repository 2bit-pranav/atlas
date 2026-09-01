"use client";

import { useEffect, useRef } from "react";
import { PanelLeftOpen, PanelRightOpen, Terminal as TerminalIcon, Trash2 } from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";

export default function TerminalPanel() {
    const open = useUIStore((s) => s.terminalOpen);
    const toggle = useUIStore((s) => s.toggleTerminal);
    const terminalLogs = useChatStore((s) => s.terminalLogs);
    const clearTerminalLogs = useChatStore((s) => s.clearTerminalLogs);
    const logsEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [terminalLogs]);

    return (
        <aside
            style={{
                width: open
                    ? "var(--terminal-width)"
                    : "var(--terminal-width-collapsed)",
                background: "var(--surface)",
                transition: "width .18s ease",
            }}
            className="flex h-full flex-col overflow-hidden"
        >
            <div
                className="flex h-14 items-center px-4 shrink-0 justify-between"
                style={{
                    borderBottom: "1px solid var(--border)",
                }}
            >
                <button onClick={toggle} className="rounded-md p-1 hover:bg-[var(--surface-hover)]">
                    {open ? (
                        <PanelLeftOpen size={18} />
                    ) : (
                        <PanelRightOpen size={18} />
                    )}
                </button>

                {open && (
                    <div className="flex items-center gap-2">
                        <TerminalIcon size={16} className="text-emerald-400" />
                        <span className="text-sm font-semibold">
                            Browser Terminal
                        </span>
                        {terminalLogs.length > 0 && (
                            <button
                                onClick={clearTerminalLogs}
                                className="ml-2 rounded p-1 hover:text-red-400 opacity-60 hover:opacity-100 transition-all"
                                title="Clear Terminal Logs"
                            >
                                <Trash2 size={14} />
                            </button>
                        )}
                    </div>
                )}
            </div>

            {open && (
                <div className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-relaxed">
                    {terminalLogs.length === 0 ? (
                        <div
                            className="rounded-xl p-3 text-xs italic"
                            style={{
                                background: "var(--background)",
                                color: "var(--muted)",
                            }}
                        >
                            Waiting for execution steps...
                        </div>
                    ) : (
                        <div
                            className="flex flex-col gap-1.5 rounded-xl p-3 shadow-inner"
                            style={{
                                background: "var(--background)",
                                border: "1px solid var(--border)",
                            }}
                        >
                            {terminalLogs.map((log, idx) => (
                                <div key={idx} className="break-words border-b border-white/5 pb-1 last:border-0 last:pb-0 text-zinc-300">
                                    {log}
                                </div>
                            ))}
                            <div ref={logsEndRef} />
                        </div>
                    )}
                </div>
            )}
        </aside>
    );
}
