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
} from "lucide-react";
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

    const chats = useChatStore((s) => s.chats);
    const activeChatId = useChatStore((s) => s.activeChatId);
    const selectChat = useChatStore((s) => s.selectChat);
    const resetChat = useChatStore((s) => s.resetChat);

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
                            <Icon size={18} className="shrink-0" />

                            {open && <span className="ml-3 truncate">{label}</span>}
                        </button>
                    ))}
                </div>

                {/* Horizontal rule below Integrations option */}
                <hr
                    className="my-2 border-t"
                    style={{ borderColor: "var(--border)" }}
                />

                {/* List of in-memory chats */}
                <div className="flex flex-1 flex-col gap-1 overflow-y-auto min-h-0">
                    {chats.map((chat) => {
                        const isActive = chat.id === activeChatId;
                        return (
                            <button
                                key={chat.id}
                                onClick={() => selectChat(chat.id)}
                                title={chat.title}
                                className="flex h-10 items-center rounded-xl px-3 text-sm text-left transition-colors"
                                style={{
                                    background: isActive
                                        ? "var(--surface-hover)"
                                        : "transparent",
                                    color: "var(--text)",
                                }}
                                onMouseEnter={(e) => {
                                    if (!isActive)
                                        e.currentTarget.style.background =
                                            "var(--surface-hover)";
                                }}
                                onMouseLeave={(e) => {
                                    if (!isActive)
                                        e.currentTarget.style.background =
                                            "transparent";
                                }}
                            >
                                <MessageSquare size={18} className="shrink-0" />

                                {open && (
                                    <span className="ml-3 truncate font-normal">
                                        {chat.title}
                                    </span>
                                )}
                            </button>
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
