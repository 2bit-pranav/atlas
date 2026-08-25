import { create } from "zustand";

export interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
}

interface ChatStore {
    messages: Message[];
    sending: boolean;
    sendMessage: (prompt: string) => Promise<void>;
    clearMessages: () => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
    messages: [],
    sending: false,

    // stream response from fastapi endpoint
    sendMessage: async (prompt: string) => {
        const trimmed = prompt.trim();
        if (!trimmed || get().sending) return;

        const userMsgId = crypto.randomUUID();
        const assistantMsgId = crypto.randomUUID();

        const userMsg: Message = { id: userMsgId, role: "user", content: trimmed };
        const assistantMsg: Message = { id: assistantMsgId, role: "assistant", content: "" };

        set((state) => ({
            messages: [...state.messages, userMsg, assistantMsg],
            sending: true,
        }));

        try {
            const response = await fetch("http://127.0.0.1:8001/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: trimmed }),
            });

            if (!response.ok || !response.body) {
                throw new Error("Failed to connect to chat endpoint");
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                set((state) => ({
                    messages: state.messages.map((msg) =>
                        msg.id === assistantMsgId
                            ? { ...msg, content: msg.content + chunk }
                            : msg
                    ),
                }));
            }
        } catch {
            set((state) => ({
                messages: state.messages.map((msg) =>
                    msg.id === assistantMsgId
                        ? { ...msg, content: "Error connecting to server." }
                        : msg
                ),
            }));
        } finally {
            set({ sending: false });
        }
    },

    clearMessages: async () => {
        set({ messages: [] });
        try {
            await fetch("http://127.0.0.1:8001/reset", { method: "POST" });
        } catch (e) {
            console.error("Failed to reset server agent history", e);
        }
    },
}));
