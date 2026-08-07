"use client";

import { PanelLeftOpen, PanelRightOpen } from "lucide-react";
import { useUIStore } from "@/stores/ui-store";

export default function TerminalPanel() {
    const open = useUIStore((s) => s.terminalOpen);
    const toggle = useUIStore((s) => s.toggleTerminal);

    return (
        <aside
            style={{
                width: open
                    ? "var(--terminal-width)"
                    : "var(--terminal-width-collapsed)",
                background: "var(--surface)",
                transition: "width .18s ease",
            }}
            className="flex h-full flex-col"
        >
            <div
                className="flex h-14 items-center px-4"
                style={{
                    borderBottom: "1px solid var(--border)",
                }}
            >
                <button onClick={toggle} className="rounded-md p-1">
                    {open ? (
                        <PanelLeftOpen size={18} />
                    ) : (
                        <PanelRightOpen size={18} />
                    )}
                </button>

                {open && (
                    <span className="ml-auto text-sm font-semibold">
                        Terminal
                    </span>
                )}
            </div>

            {open && (
                <div className="p-3">
                    <div
                        className="rounded-xl p-3 text-sm"
                        style={{
                            background: "var(--background)",
                            color: "var(--muted)",
                        }}
                    >
                        Waiting for execution...
                    </div>
                </div>
            )}
        </aside>
    );
}
