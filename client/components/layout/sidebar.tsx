"use client";

import {
    Brain,
    Globe,
    History,
    Plug,
    SunIcon,
    MoonIcon,
    PlusIcon,
    PanelLeftOpen,
    PanelRightOpen,
} from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";

const items = [
    { icon: PlusIcon, label: "New Chat", action: "new" },
    { icon: History, label: "Chat History" },
    { icon: Globe, label: "Browser Profiles" },
    { icon: Brain, label: "Saved Memory" },
    { icon: Plug, label: "Integrations" },
];

export default function Sidebar() {
    const open = useUIStore((s) => s.sidebarOpen);
    const toggle = useUIStore((s) => s.toggleSidebar);
    const theme = useUIStore((s) => s.theme);
    const toggleTheme = useUIStore((s) => s.toggleTheme);
    const clearMessages = useChatStore((s) => s.clearMessages);

    return (
        <aside
            style={{
                width: open
                    ? "var(--sidebar-width)"
                    : "var(--sidebar-width-collapsed)",
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
                {open && (
                    <h1
                        className="flex-1 text-[18px] font-semibold"
                        style={{ color: "var(--text)" }}
                    >
                        Atlas
                    </h1>
                )}

                <button
                    onClick={toggle}
                    className="rounded-md p-1"
                    style={{
                        background: "transparent",
                    }}
                >
                    {open ? (
                        <PanelRightOpen size={18} />
                    ) : (
                        <PanelLeftOpen size={18} />
                    )}
                </button>
            </div>

            <div className="flex flex-1 flex-col gap-1 p-2">
                {items.map(({ icon: Icon, label, action }) => (
                    <button
                        key={label}
                        onClick={action === "new" ? clearMessages : undefined}
                        className="flex h-10 items-center rounded-xl px-3 text-sm"
                        style={{
                            background: "transparent",
                        }}
                        onMouseEnter={(e) =>
                            (e.currentTarget.style.background =
                                "var(--surface-hover)")
                        }
                        onMouseLeave={(e) =>
                            (e.currentTarget.style.background = "transparent")
                        }
                    >
                        <Icon size={18} />

                        {open && <span className="ml-3">{label}</span>}
                    </button>
                ))}
            </div>

            <div
                className="p-2"
                style={{
                    borderTop: "1px solid var(--border)",
                }}
            >
                <button
                    type="button"
                    onClick={toggleTheme}
                    className="flex h-10 w-full items-center rounded-xl px-3 text-sm"
                    style={{
                        background: "transparent",
                    }}
                    onMouseEnter={(e) =>
                        (e.currentTarget.style.background =
                            "var(--surface-hover)")
                    }
                    onMouseLeave={(e) =>
                        (e.currentTarget.style.background = "transparent")
                    }
                >
                    {theme === "dark" ? (
                        <SunIcon size={18} />
                    ) : (
                        <MoonIcon size={18} />
                    )}

                    {open && <span className="ml-3">Theme</span>}
                </button>
            </div>
        </aside>
    );
}
