import { create } from "zustand";

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
    setActiveChatId: (chatId: string | null) => void;
    fetchSessions: () => Promise<void>;
    deleteSession: (chatId: string) => Promise<void>;
    updateSessionTitle: (chatId: string, title: string) => Promise<void>;
}

const API_BASE = "http://localhost:8001/api/sessions";

export const useSessionStore = create<SessionState>((set, get) => ({
    sessions: [],
    activeChatId: null,
    isLoadingSessions: false,

    setActiveChatId: (activeChatId) => set({ activeChatId }),

    fetchSessions: async () => {
        set({ isLoadingSessions: true });
        try {
            const res = await fetch(API_BASE);
            if (res.ok) {
                const data = await res.json();
                set({ sessions: Array.isArray(data) ? data : [] });
            } else {
                set({ sessions: [] });
            }
        } catch {
            set({ sessions: [] });
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
                }
                void get().fetchSessions();
            }
        } catch {
            // Fail silently if offline
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
            // Fail silently if offline
        }
    },
}));