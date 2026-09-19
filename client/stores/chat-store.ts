import { create } from "zustand";
import { useSessionStore } from "./session-store";

export interface ChatAttachment {
    name: string;
    type: "image" | "document";
    path?: string;
}

export type MessageStatus = "running" | "completed" | "cancelled" | "error";

export interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    status: MessageStatus;
    thought?: string;
    attachments?: ChatAttachment[];
}

export interface ChatState {
    messages: Message[];
    terminalLogs: string[];
    currentStatus: string | null;
    isLoading: boolean;
    error: string | null;
    useCloud: boolean;
    thinkingBudget: number;

    setUseCloud: (useCloud: boolean) => void;
    setThinkingBudget: (budget: number) => void;
    clearError: () => void;
    clearTerminalLogs: () => void;
    resetChat: () => void;

    loadSessionMessages: (chatId: string) => Promise<void>;
    sendMessage: (prompt: string, attachmentFiles?: Array<string | File>) => Promise<void>;
    stopGeneration: () => Promise<void>;
    editMessage: (messageId: string, newPrompt: string) => Promise<void>;
    retryMessage: (messageId: string) => Promise<void>;
}

let activeAbortController: AbortController | null = null;
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
const API_BASE = `${BACKEND_URL}/api`;

async function processStream(
    response: Response,
    assistantMessageId: string,
    set: (fn: (state: ChatState) => Partial<ChatState>) => void,
): Promise<void> {
    const reader = response.body?.getReader();
    if (!reader) throw new Error("Response body is null");

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
                const rawJson = trimmed.slice(6).trim();
                if (!rawJson) continue;

                try {
                    const parsed = JSON.parse(rawJson) as Record<string, unknown>;
                    const type = String(parsed.type || "");

                    if (type === "meta" && typeof parsed.chat_id === "string") {
                        useSessionStore.getState().setActiveChatId(parsed.chat_id);
                    } else if (type === "status") {
                        if (parsed.status === "stopped") {
                            set((state) => ({
                                currentStatus: null,
                                messages: state.messages.map((m) =>
                                    m.id === assistantMessageId ? { ...m, status: "cancelled" } : m
                                ),
                            }));
                        } else if (parsed.status === "completed") {
                            set((state) => ({
                                currentStatus: null,
                                messages: state.messages.map((m) =>
                                    m.id === assistantMessageId ? { ...m, status: "completed" } : m
                                ),
                            }));
                        } else {
                            const label = typeof parsed.label === "string" ? parsed.label : null;
                            if (label && label !== "Thinking...") {
                                set(() => ({ currentStatus: label }));
                            }
                        }
                    } else if (type === "thought" && typeof parsed.content === "string") {
                        set((state) => ({
                            currentStatus: null,
                            messages: state.messages.map((msg) =>
                                msg.id === assistantMessageId
                                    ? { ...msg, thought: (msg.thought || "") + (parsed.content as string) }
                                    : msg
                            ),
                        }));
                    } else if (type === "chunk" && typeof parsed.content === "string") {
                        set((state) => ({
                            currentStatus: null,
                            messages: state.messages.map((msg) =>
                                msg.id === assistantMessageId
                                    ? { ...msg, content: msg.content + (parsed.content as string) }
                                    : msg
                            ),
                        }));
                    } else if (type === "error" && typeof parsed.detail === "string") {
                        set((state) => ({
                            error: parsed.detail as string,
                            messages: state.messages.map((m) =>
                                m.id === assistantMessageId
                                    ? { ...m, status: "error", content: m.content || `⚠️ **Error:** ${parsed.detail}` }
                                    : m
                            ),
                        }));
                    } else if (type === "terminal" && typeof parsed.content === "string") {
                        set((state) => ({
                            terminalLogs: [...state.terminalLogs, parsed.content as string],
                        }));
                    }
                } catch (err: unknown) {
                    console.warn("Failed to parse SSE line:", rawJson, err);
                }
            }
        }
    }
}

export const useChatStore = create<ChatState>((set, get) => ({
    messages: [],
    terminalLogs: [],
    currentStatus: null,
    isLoading: false,
    error: null,
    useCloud: false,
    thinkingBudget: 0,

    setUseCloud: (useCloud) => set(() => ({ useCloud })),
    setThinkingBudget: (thinkingBudget) => set(() => ({ thinkingBudget })),
    clearError: () => set(() => ({ error: null })),
    clearTerminalLogs: () => set(() => ({ terminalLogs: [] })),

    resetChat: () => {
        useSessionStore.getState().setActiveChatId(null);
        set(() => ({
            messages: [],
            terminalLogs: [],
            currentStatus: null,
            error: null,
            isLoading: false,
        }));
    },

    loadSessionMessages: async (chatId: string) => {
        set(() => ({ isLoading: true, error: null }));
        try {
            const res = await fetch(`${API_BASE}/sessions/${chatId}`);
            if (!res.ok) throw new Error("Failed to load chat history");
            const data = await res.json();
            const normalizedMessages: Message[] = (data.messages || []).map((m: Partial<Message>) => ({
                ...m,
                status: m.status || (m.content?.includes("*Response was cancelled*") ? "cancelled" : "completed"),
            }));
            useSessionStore.getState().setActiveChatId(data.id);
            set(() => ({ messages: normalizedMessages }));
        } catch (err: unknown) {
            set(() => ({ error: err instanceof Error ? err.message : "Failed to load session" }));
        } finally {
            set(() => ({ isLoading: false }));
        }
    },

    stopGeneration: async () => {
        const activeChatId = useSessionStore.getState().activeChatId;
        if (activeAbortController) {
            activeAbortController.abort();
            activeAbortController = null;
        }
        if (activeChatId) {
            try {
                await fetch(`${API_BASE}/chat/${activeChatId}/stop`, { method: "POST" });
            } catch (err: unknown) {
                console.warn("Failed to send stop signal:", err);
            }
        }
        set((state) => {
            const lastAssistantIdx = state.messages.findLastIndex((m) => m.role === "assistant");
            return {
                isLoading: false,
                currentStatus: null,
                messages: state.messages.map((m, idx) =>
                    idx === lastAssistantIdx ? { ...m, status: "cancelled" } : m
                ),
            };
        });
    },

    sendMessage: async (prompt: string, attachmentFiles?: Array<string | File>) => {
        const { useCloud, thinkingBudget } = get();
        const activeChatId = useSessionStore.getState().activeChatId;

        const userMessageId = `msg_${Date.now()}`;
        const assistantMessageId = `msg_${Date.now() + 1}`;

        const attachmentsMeta: ChatAttachment[] = (attachmentFiles || []).map((f) => {
            if (typeof f === "string")
                return {
                    name: f.split(/[/\\]/).pop() || f,
                    path: f,
                    type: "document",
                };
            return {
                name: f.name,
                type: f.type.startsWith("image/") ? "image" : "document",
            };
        });

        const userMessage: Message = {
            id: userMessageId,
            role: "user",
            content: prompt,
            attachments: attachmentsMeta,
            status: "completed",
        };

        const assistantPlaceholder: Message = {
            id: assistantMessageId,
            role: "assistant",
            content: "",
            thought: "",
            status: "running",
        };

        set((state) => ({
            messages: [...state.messages, userMessage, assistantPlaceholder],
            isLoading: true,
            error: null,
            currentStatus: null,
        }));

        activeAbortController = new AbortController();

        try {
            const formData = new FormData();
            formData.append("prompt", prompt);
            formData.append("user_message_id", userMessageId);
            formData.append("assistant_message_id", assistantMessageId);
            formData.append("use_cloud", String(useCloud));
            formData.append("thinking_budget", String(thinkingBudget));
            if (activeChatId) {
                formData.append("chat_id", activeChatId);
            }

            (attachmentFiles || []).forEach((file) => {
                if (typeof file === "string") {
                    formData.append("file_paths", file);
                } else {
                    formData.append("files", file);
                }
            });

            const response = await fetch(`${API_BASE}/chat`, {
                method: "POST",
                body: formData,
                signal: activeAbortController.signal,
            });

            if (!response.ok) {
                const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
                throw new Error(errorData.detail || `Server error ${response.status}`);
            }

            await processStream(response, assistantMessageId, set);

            set((state) => ({
                messages: state.messages.map((m) =>
                    m.id === assistantMessageId && m.status === "running"
                        ? { ...m, status: "completed" }
                        : m
                ),
            }));
            void useSessionStore.getState().fetchSessions();
        } catch (err: unknown) {
            if (err instanceof Error && err.name === "AbortError") {
                return;
            }
            const errMsg = err instanceof Error ? err.message : "Error sending message";
            set((state) => ({
                error: errMsg,
                messages: state.messages.map((m) =>
                    m.id === assistantMessageId
                        ? { ...m, status: "error", content: `⚠️ **Error:** ${errMsg}` }
                        : m
                ),
            }));
        } finally {
            activeAbortController = null;
            set(() => ({ isLoading: false, currentStatus: null }));
        }
    },

    editMessage: async (messageId: string, newPrompt: string) => {
        const activeChatId = useSessionStore.getState().activeChatId;
        const { useCloud, thinkingBudget } = get();
        const assistantMessageId = `msg_${Date.now()}`;

        let targetAttachments: ChatAttachment[] = [];
        set((state) => {
            const targetIdx = state.messages.findIndex((m) => m.id === messageId);
            if (targetIdx === -1) return state;
            const existingMsg = state.messages[targetIdx];
            targetAttachments = existingMsg.attachments || [];
            const updated = state.messages.slice(0, targetIdx);

            return {
                messages: [
                    ...updated,
                    {
                        id: messageId,
                        role: "user",
                        content: newPrompt,
                        attachments: targetAttachments,
                        status: "completed",
                    },
                    {
                        id: assistantMessageId,
                        role: "assistant",
                        content: "",
                        thought: "",
                        status: "running",
                    },
                ],
                isLoading: true,
                error: null,
                currentStatus: null,
            };
        });

        if (!activeChatId) {
            set(() => ({ error: "Active session not found. Please refresh." }));
            return;
        }

        activeAbortController = new AbortController();

        try {
            const response = await fetch(
                `${API_BASE}/chat/${activeChatId}/messages/${messageId}/edit`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        new_prompt: newPrompt,
                        use_cloud: useCloud,
                        thinking_budget: thinkingBudget,
                    }),
                    signal: activeAbortController.signal,
                },
            );

            if (!response.ok) throw new Error("Failed to edit message");

            await processStream(response, assistantMessageId, set);

            set((state) => ({
                messages: state.messages.map((m) =>
                    m.id === assistantMessageId && m.status === "running"
                        ? { ...m, status: "completed" }
                        : m
                ),
            }));
            void useSessionStore.getState().fetchSessions();
        } catch (err: unknown) {
            if (err instanceof Error && err.name === "AbortError") {
                return;
            }
            const errMsg = err instanceof Error ? err.message : "Error editing message";
            set((state) => ({
                error: errMsg,
                messages: state.messages.map((m) =>
                    m.id === assistantMessageId
                        ? { ...m, status: "error", content: `⚠️ **Error:** ${errMsg}` }
                        : m
                ),
            }));
        } finally {
            activeAbortController = null;
            set(() => ({ isLoading: false, currentStatus: null }));
        }
    },

    retryMessage: async (messageId: string) => {
        const activeChatId = useSessionStore.getState().activeChatId;
        if (!activeChatId) {
            set(() => ({ error: "Active session not found. Please refresh." }));
            return;
        }

        const { useCloud, thinkingBudget } = get();

        set((state) => ({
            messages: state.messages.map((m) =>
                m.id === messageId
                    ? { ...m, content: "", thought: "", status: "running" }
                    : m
            ),
            isLoading: true,
            error: null,
            currentStatus: null,
        }));

        activeAbortController = new AbortController();

        try {
            const response = await fetch(
                `${API_BASE}/chat/${activeChatId}/messages/${messageId}/retry`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        use_cloud: useCloud,
                        thinking_budget: thinkingBudget,
                    }),
                    signal: activeAbortController.signal,
                },
            );

            if (!response.ok) {
                const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
                throw new Error(errorData.detail || `Server error ${response.status}`);
            }

            await processStream(response, messageId, set);

            set((state) => ({
                messages: state.messages.map((m) =>
                    m.id === messageId && m.status === "running"
                        ? { ...m, status: "completed" }
                        : m
                ),
            }));
            void useSessionStore.getState().fetchSessions();
        } catch (err: unknown) {
            if (err instanceof Error && err.name === "AbortError") {
                return;
            }
            const errMsg = err instanceof Error ? err.message : "Error retrying message";
            set((state) => ({
                error: errMsg,
                messages: state.messages.map((m) =>
                    m.id === messageId
                        ? { ...m, status: "error", content: `⚠️ **Error:** ${errMsg}` }
                        : m
                ),
            }));
        } finally {
            activeAbortController = null;
            set(() => ({ isLoading: false, currentStatus: null }));
        }
    },
}));