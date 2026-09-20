"use client";
import {
    Brain,
    // Globe,
    Lightbulb,
    Plug,
    SunIcon,
    MoonIcon,
    PlusIcon,
    PanelLeftOpen,
    PanelRightOpen,
    MessageSquare,
    Trash2,
    Settings,
} from "lucide-react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUIStore } from "@/stores/ui-store";
import { useChatStore } from "@/stores/chat-store";
import { useSessionStore } from "@/stores/session-store";
import Link from "next/link";

const items = [
    { icon: PlusIcon, label: "New Chat", isNewChat: true },
    { icon: Brain, label: "Manage Memory", href: "/memory" },
    // { icon: Globe, label: "Browser Sessions", href: "/browser-sessions" },
    { icon: Lightbulb, label: "Manage Skills", href: "/skills" },
    { icon: Plug, label: "Integrations", href: "/integrations" },
];

export default function Sidebar() {
    const router = useRouter();
    const open = useUIStore((s) => s.sidebarOpen);
    const toggle = useUIStore((s) => s.toggleSidebar);
    const theme = useUIStore((s) => s.theme);
    const toggleTheme = useUIStore((s) => s.toggleTheme);

    // Chat store: manages streaming turn state & chat reset
    const isLoading = useChatStore((s) => s.isLoading);
    const loadSessionMessages = useChatStore((s) => s.loadSessionMessages);
    const resetChat = useChatStore((s) => s.resetChat);

    // Session store: manages persistent session list & active selection
    const sessions = useSessionStore((s) => s.sessions);
    const sessionsError = useSessionStore((s) => s.sessionsError);
    const isLoadingSessions = useSessionStore((s) => s.isLoadingSessions);
    const activeChatId = useSessionStore((s) => s.activeChatId);
    const fetchSessions = useSessionStore((s) => s.fetchSessions);
    const deleteSession = useSessionStore((s) => s.deleteSession);

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
                    style={{ background: "transparent" }}
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
                    {items.map(({ icon: Icon, label, isNewChat, href }) => (
                        isNewChat ? (
                            <button
                                key={label}
                                onClick={() => {
                                    resetChat();
                                    router.push("/");
                                }}
                                className="flex h-10 items-center rounded-xl px-3 text-sm font-medium hover:bg-[var(--surface-hover)] hover:cursor-pointer transition-colors"
                            >
                                <Icon size={18} className="shrink-0" />
                                {open && <span className="ml-3 truncate">{label}</span>}
                            </button>
                        ) : (
                            <Link
                                key={label}
                                href={href || "#"}
                                className="flex h-10 items-center rounded-xl px-3 text-sm font-medium hover:bg-[var(--surface-hover)] transition-colors"
                            >
                                <Icon size={18} className="shrink-0" />
                                {open && <span className="ml-3 truncate">{label}</span>}
                            </Link>
                        )
                    ))}
                </div>

                <hr
                    className="my-2 border-t"
                    style={{ borderColor: "var(--border)" }}
                />

                {/* Persisted Sessions List */}
                <div className="flex flex-1 flex-col gap-1 overflow-y-auto min-h-0">
                    {sessionsError && open && (
                        <div className="mx-2 my-1 rounded-lg text-sm">
                            <p>{sessionsError}</p>
                            <button
                                type="button"
                                onClick={() => void fetchSessions()}
                                className="mt-1 font-medium underline hover:cursor-pointer"
                            >
                                Retry connection
                            </button>
                        </div>
                    )}

                    {!sessionsError && sessions.length === 0 && open && !isLoadingSessions && (
                        <p className="px-3 py-2 text-xs text-neutral-500 italic">No chat history yet</p>
                    )}

                    {(sessions ?? []).map((session) => {
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
                                onClick={() => {
                                    router.push("/");
                                    if (session.id !== activeChatId || !isLoading) {
                                        void loadSessionMessages(session.id);
                                    }
                                }}
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
                style={{ borderTop: "1px solid var(--border)" }}
            >
                <div className="flex gap-2">
                    <Link
                        href="/settings"
                        className="flex h-10 flex-1 items-center rounded-xl px-3 text-sm font-medium hover:bg-[var(--surface-hover)]"
                    >
                        <Settings size={18} className="shrink-0" />
                        {open && <span className="ml-3 truncate">Settings</span>}
                    </Link>
                    <button
                        type="button"
                        onClick={toggleTheme}
                        className="flex h-10 w-10 items-center justify-center rounded-xl shrink-0 hover:bg-[var(--surface-hover)]"
                        title={theme === "dark" ? "Light mode" : "Dark mode"}
                    >
                        {theme === "dark" ? (
                            <SunIcon size={18} />
                        ) : (
                            <MoonIcon size={18} />
                        )}
                    </button>
                </div>
            </div>
        </aside>
    );
}