"use client";

import {
    Brain,
    Globe,
    Lightbulb,
    Plug,
    SunIcon,
    MoonIcon,
    PlusIcon,
    PanelLeftOpen,
    PanelRightOpen,
    MessageSquare,
    Trash2,
} from "lucide-react";
import { useEffect } from "react";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";

const items = [
    { icon: PlusIcon, label: "New Chat", isNewChat: true },
    { icon: Brain, label: "Manage Memory" },
    { icon: Globe, label: "Browser Sessions" },
    { icon: Lightbulb, label: "Manage Skills" },
    { icon: Plug, label: "Integrations" },
];

export default function Sidebar() {
    const open = useUIStore((s) => s.sidebarOpen);
    const toggle = useUIStore((s) => s.toggleSidebar);
    const theme = useUIStore((s) => s.theme);
    const toggleTheme = useUIStore((s) => s.toggleTheme);

    const activeChatId = useChatStore((s) => s.activeChatId);
    const sessions = useChatStore((s) => s.sessions);
    const fetchSessions = useChatStore((s) => s.fetchSessions);
    const loadSession = useChatStore((s) => s.loadSession);
    const deleteSession = useChatStore((s) => s.deleteSession);
    const resetChat = useChatStore((s) => s.resetChat);

    useEffect(() => {
        void fetchSessions();
    }, [fetchSessions]);

    return (
        <aside
            style={{
                width: open
                    ? "var(--sidebar-width)"
                    : "var(--sidebar-width-collapsed)",
                background: "var(--surface)",
                transition: "width .18s ease",
            }}
            className="flex h-full flex-col overflow-hidden"
        >
            <div
                className="flex h-14 items-center px-4 shrink-0"
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

            <div className="flex flex-1 flex-col overflow-hidden p-2">
                <div className="flex flex-col gap-1 shrink-0">
                    {items.map(({ icon: Icon, label, isNewChat }) => (
                        <button
                            key={label}
                            onClick={() => {
                                if (isNewChat) {
                                    resetChat();
                                }
                            }}
                            className="flex h-10 items-center rounded-xl px-3 text-sm font-medium"
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
                            <Icon size={18} className="shrink-0" />

                            {open && <span className="ml-3 truncate">{label}</span>}
                        </button>
                    ))}
                </div>

                {/* Horizontal rule below options */}
                <hr
                    className="my-2 border-t"
                    style={{ borderColor: "var(--border)" }}
                />

                {/* List of in-memory chat sessions */}
                <div className="flex flex-1 flex-col gap-1 overflow-y-auto min-h-0">
                    {sessions.map((session) => {
                        const isActive = session.id === activeChatId;
                        return (
                            <div
                                key={session.id}
                                className="group flex items-center justify-between rounded-xl px-3 h-10 text-sm transition-colors cursor-pointer"
                                style={{
                                    background: isActive
                                        ? "var(--surface-hover)"
                                        : "transparent",
                                    color: "var(--text)",
                                }}
                                onClick={() => void loadSession(session.id)}
                            >
                                <div className="flex items-center min-w-0 flex-1">
                                    <MessageSquare size={18} className="shrink-0 opacity-70" />

                                    {open && (
                                        <span className="ml-3 truncate font-normal text-xs" title={session.title}>
                                            {session.title}
                                        </span>
                                    )}
                                </div>

                                {open && (
                                    <button
                                        type="button"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            void deleteSession(session.id);
                                        }}
                                        className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-opacity rounded"
                                        title="Delete chat session"
                                    >
                                        <Trash2 size={13} />
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>

            <div
                className="p-2 shrink-0"
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
