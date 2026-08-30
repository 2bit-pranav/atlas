import { create } from "zustand";

export interface ChatAttachment {
    name: string;
    path?: string;
    type?: "image" | "document";
}

export interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    thought?: string;
    attachments?: ChatAttachment[];
}

export interface ChatRequestPayload {
    prompt: string;
    chat_id?: string | null;
    thinking_budget?: number;
    use_cloud?: boolean;
    attachments?: string[];
}

export interface ChatSessionMeta {
    id: string;
    title: string;
    created_at?: string;
    updated_at?: string;
}

export interface ChatState {
    messages: Message[];
    sessions: ChatSessionMeta[];
    activeChatId: string | null;
    isLoading: boolean;
    error: string | null;
    useCloud: boolean;
    thinkingBudget: number;

    setUseCloud: (useCloud: boolean) => void;
    setThinkingBudget: (budget: number) => void;
    setActiveChatId: (chatId: string | null) => void;
    clearError: () => void;
    resetChat: () => void;
    fetchSessions: () => Promise<void>;
    loadSession: (chatId: string) => Promise<void>;
    deleteSession: (chatId: string) => Promise<void>;
    sendMessage: (
        prompt: string,
        attachmentFiles?: Array<string | File>,
    ) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
    messages: [],
    sessions: [],
    activeChatId: null,
    isLoading: false,
    error: null,
    useCloud: false,
    thinkingBudget: 0,

    setUseCloud: (useCloud) => set({ useCloud }),
    setThinkingBudget: (thinkingBudget) => set({ thinkingBudget }),
    setActiveChatId: (activeChatId) => set({ activeChatId }),
    clearError: () => set({ error: null }),

    resetChat: () =>
        set({
            messages: [],
            activeChatId: null,
            error: null,
            isLoading: false,
        }),

    fetchSessions: async () => {
        try {
            const res = await fetch("http://localhost:8001/api/sessions");
            if (res.ok) {
                const data = await res.json();
                set({ sessions: data });
            }
        } catch (err) {
            console.error("Failed to fetch sessions:", err);
        }
    },

    loadSession: async (chatId: string) => {
        set({ isLoading: true, error: null });
        try {
            const res = await fetch(`http://localhost:8001/api/sessions/${chatId}`);
            if (!res.ok) {
                throw new Error("Failed to load chat session");
            }
            const data = await res.json();
            set({
                activeChatId: data.id,
                messages: data.messages || [],
            });
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : "Error loading session";
            set({ error: msg });
        } finally {
            set({ isLoading: false });
        }
    },

    deleteSession: async (chatId: string) => {
        try {
            const res = await fetch(`http://localhost:8001/api/sessions/${chatId}`, {
                method: "DELETE",
            });
            if (res.ok) {
                const { activeChatId } = get();
                if (activeChatId === chatId) {
                    get().resetChat();
                }
                void get().fetchSessions();
            }
        } catch (err) {
            console.error("Failed to delete session:", err);
        }
    },

    sendMessage: async (
        prompt: string,
        attachmentFiles: Array<string | File> = [],
    ) => {
        const cleanPrompt = prompt.trim();
        if (!cleanPrompt && attachmentFiles.length === 0) return;

        const { activeChatId, useCloud, thinkingBudget, messages } = get();

        const userAttachments: ChatAttachment[] = attachmentFiles.map((file) => {
            if (file instanceof File) {
                return {
                    name: file.name,
                    type: file.type.startsWith("image/") ? "image" : "document",
                };
            }
            const strFile = String(file);
            const isImg = /\.(png|jpe?g|webp|gif|bmp)$/i.test(strFile);
            return {
                name: strFile.split(/[\/\\]/).pop() || strFile,
                type: isImg ? "image" : "document",
            };
        });

        const userMessage: Message = {
            id: crypto.randomUUID(),
            role: "user",
            content: cleanPrompt,
            attachments: userAttachments,
        };

        const assistantMessageId = crypto.randomUUID();
        const assistantMessage: Message = {
            id: assistantMessageId,
            role: "assistant",
            content: "",
            thought: "",
        };

        set({
            messages: [...messages, userMessage, assistantMessage],
            isLoading: true,
            error: null,
        });

        try {
            const formData = new FormData();
            formData.append("prompt", cleanPrompt);
            if (activeChatId) formData.append("chat_id", activeChatId);
            formData.append("thinking_budget", String(thinkingBudget));
            formData.append("use_cloud", String(useCloud));

            attachmentFiles.forEach((attachment) => {
                if (attachment instanceof File) {
                    formData.append("attachments", attachment, attachment.name);
                    return;
                }

                if (attachment && attachment.trim()) {
                    formData.append("attachments", attachment);
                }
            });

            const response = await fetch("http://localhost:8001/api/chat", {
                method: "POST",
                body: formData,
            });

            if (!response.ok || !response.body) {
                throw new Error(
                    `HTTP ${response.status}: ${response.statusText}`,
                );
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.startsWith("data: ")) {
                        const rawJson = trimmed.replace("data: ", "").trim();
                        if (!rawJson) continue;

                        try {
                            const parsed = JSON.parse(rawJson);
                            if (parsed.type === "meta" && parsed.chat_id) {
                                set({ activeChatId: parsed.chat_id });
                            } else if (
                                parsed.type === "thought" &&
                                parsed.content
                            ) {
                                set((state) => ({
                                    messages: state.messages.map((msg) =>
                                        msg.id === assistantMessageId
                                            ? {
                                                  ...msg,
                                                  thought:
                                                      (msg.thought || "") +
                                                      parsed.content,
                                              }
                                            : msg,
                                    ),
                                }));
                            } else if (
                                parsed.type === "chunk" &&
                                parsed.content
                            ) {
                                set((state) => ({
                                    messages: state.messages.map((msg) =>
                                        msg.id === assistantMessageId
                                            ? {
                                                  ...msg,
                                                  content:
                                                      msg.content +
                                                      parsed.content,
                                              }
                                            : msg,
                                    ),
                                }));
                            }
                        } catch (err) {
                            console.warn(
                                "Failed to parse SSE line:",
                                rawJson,
                                err,
                            );
                        }
                    }
                }
            }
        } catch (err: unknown) {
            console.error("Chat streaming failed:", err);
            const message =
                err instanceof Error ? err.message : "Communication error";

            set((state) => {
                const msg = state.messages.find(
                    (m) => m.id === assistantMessageId,
                );
                return {
                    error: message,
                    messages: msg?.content
                        ? state.messages
                        : state.messages.filter(
                              (m) => m.id !== assistantMessageId,
                          ),
                };
            });
        } finally {
            set({ isLoading: false });
            void get().fetchSessions();
        }
    },
}));
