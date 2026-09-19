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
    isLoadingSessions: boolean;
    sessionsError: string | null;
    setActiveChatId: (chatId: string | null) => void;
    fetchSessions: () => Promise<void>;
    deleteSession: (chatId: string) => Promise<void>;
    updateSessionTitle: (chatId: string, title: string) => Promise<void>;
}

const API_BASE = "/api/sessions";

export const useSessionStore = create<SessionState>((set, get) => ({
    sessions: [],
    activeChatId: null,
    isLoadingSessions: false,
    sessionsError: null,

    setActiveChatId: (activeChatId) => set({ activeChatId }),

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
                    set({ activeChatId: null });
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
}));