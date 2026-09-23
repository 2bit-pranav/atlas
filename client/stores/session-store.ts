import { create } from "zustand";
import { useChatStore } from "./chat-store";

export interface ChatSessionMeta {
    id: string;
    title: string;
    created_at?: string;
    updated_at?: string;
    message_count?: number;
}

interface SessionState {
    sessions: ChatSessionMeta[];
    activeChatId: string | null;
    activeMountedFolder: string | null;
    isLoadingSessions: boolean;
    sessionsError: string | null;
    setActiveChatId: (chatId: string | null) => void;
    fetchSessions: () => Promise<void>;
    deleteSession: (chatId: string) => Promise<void>;
    updateSessionTitle: (chatId: string, title: string) => Promise<void>;
    browseAndMount: (chatId?: string | null) => Promise<boolean>;
    unmountFolder: (chatId: string) => Promise<boolean>;
    fetchActiveMount: (chatId: string) => Promise<void>;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
const API_BASE = `${BACKEND_URL}/api/sessions`;

export const useSessionStore = create<SessionState>((set, get) => ({
    sessions: [],
    activeChatId: null,
    activeMountedFolder: null,
    isLoadingSessions: false,
    sessionsError: null,

    setActiveChatId: (activeChatId) =>
        set({
            activeChatId,
            // Reset mounted folder badge if starting a fresh chat
            activeMountedFolder: activeChatId ? get().activeMountedFolder : null,
        }),

    fetchSessions: async () => {
        set({ isLoadingSessions: true, sessionsError: null });
        try {
            const res = await fetch(API_BASE);
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            const data = await res.json();
            set({ sessions: Array.isArray(data) ? data : [], sessionsError: null });
        } catch {
            set({ sessionsError: "Unable to load chats" });
        } finally {
            set({ isLoadingSessions: false });
        }
    },

    deleteSession: async (chatId: string) => {
        try {
            const res = await fetch(`${API_BASE}/${chatId}`, { method: "DELETE" });
            if (res.ok) {
                const { activeChatId } = get();
                if (activeChatId === chatId) {
                    set({ activeChatId: null, activeMountedFolder: null });
                    useChatStore.getState().resetChat();
                }
                void get().fetchSessions();
            }
        } catch {
            // Handled gracefully
        }
    },

    updateSessionTitle: async (chatId: string, title: string) => {
        try {
            const res = await fetch(`${API_BASE}/${chatId}/title`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title }),
            });
            if (res.ok) {
                void get().fetchSessions();
            }
        } catch {
            // Handled gracefully
        }
    },

    browseAndMount: async (chatId?: string | null) => {
        try {
            // If on a new chat, auto-create a session ID so mounting works immediately
            let targetId = chatId;
            if (!targetId) {
                targetId = crypto.randomUUID();
                set({ activeChatId: targetId });
            }

            const res = await fetch(`${API_BASE}/${targetId}/browse-mount`, {
                method: "POST",
            });
            if (res.ok) {
                const data = await res.json();
                if (!data.cancelled && data.mounted_folder) {
                    set({ activeMountedFolder: data.mounted_folder });
                    return true;
                }
            }
            return false;
        } catch {
            return false;
        }
    },

    unmountFolder: async (chatId: string) => {
        try {
            const res = await fetch(`${API_BASE}/${chatId}/mount`, {
                method: "DELETE",
            });
            if (res.ok) {
                set({ activeMountedFolder: null });
                return true;
            }
            return false;
        } catch {
            return false;
        }
    },

    fetchActiveMount: async (chatId: string) => {
        try {
            const res = await fetch(`${API_BASE}/${chatId}`);
            if (res.ok) {
                const data = await res.json();
                set({ activeMountedFolder: data.mounted_folder || null });
            }
        } catch {
            set({ activeMountedFolder: null });
        }
    },
}));