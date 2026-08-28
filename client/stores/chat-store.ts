import { create } from "zustand";

export interface Message {
    id: string;
    role: "user" | "assistant";
    content: string;
    thought?: string;
}

export interface ChatRequest {
    prompt: string;
    chat_id?: string | null;
    thinking_budget?: number;
    use_cloud?: boolean;
}

export interface Chat {
    id: string;
    title: string;
    messages: Message[];
}

export interface ChatState {
    // State
    messages: Message[];
    chats: Chat[];
    activeChatId: string | null;
    isLoading: boolean;
    sending: boolean;
    error: string | null;
    useCloud: boolean;
    thinkingBudget: number;

    // Setters & Actions
    setUseCloud: (useCloud: boolean) => void;
    setThinkingBudget: (budget: number) => void;
    setActiveChatId: (chatId: string | null) => void;
    clearError: () => void;
    resetChat: () => void;
    selectChat: (chatId: string) => void;
    sendMessage: (prompt: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
    messages: [],
    chats: [],
    activeChatId: null,
    isLoading: false,
    sending: false,
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
            sending: false,
        }),

    selectChat: (chatId: string) => {
        const { chats } = get();
        const targetChat = chats.find((c) => c.id === chatId);
        if (targetChat) {
            set({
                activeChatId: chatId,
                messages: targetChat.messages,
                error: null,
            });
        }
    },

    sendMessage: async (prompt: string) => {
        const cleanPrompt = prompt.trim();
        if (!cleanPrompt) return;

        const { activeChatId, useCloud, thinkingBudget, messages, chats } = get();

        // Generate chat title by truncating after the first 2-3 words
        const defaultTitle = cleanPrompt.split(/\s+/).slice(0, 3).join(" ");

        // 1. Optimistically append user message and empty assistant placeholder
        const userMessage: Message = {
            id: crypto.randomUUID(),
            role: "user",
            content: cleanPrompt,
        };

        const assistantMessageId = crypto.randomUUID();
        const assistantMessage: Message = {
            id: assistantMessageId,
            role: "assistant",
            content: "",
            thought: "",
        };

        const nextMessages = [...messages, userMessage, assistantMessage];

        // Update chats array if activeChatId already exists
        const updatedChats = activeChatId
            ? chats.map((c) =>
                  c.id === activeChatId ? { ...c, messages: nextMessages } : c
              )
            : chats;

        set({
            messages: nextMessages,
            chats: updatedChats,
            isLoading: true,
            sending: true,
            error: null,
        });

        try {
            const payload: ChatRequest = {
                prompt: cleanPrompt,
                chat_id: activeChatId,
                thinking_budget: thinkingBudget,
                use_cloud: useCloud,
            };

            const response = await fetch("http://localhost:8001/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                throw new Error(
                    `Server returned HTTP status ${response.status}: ${response.statusText}`,
                );
            }

            if (!response.body) {
                throw new Error(
                    "No readable response body received from server.",
                );
            }

            // 2. Read SSE stream
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

                            // Capture server generated chat_id
                            if (parsed.type === "meta" && parsed.chat_id) {
                                const currentChatId = parsed.chat_id;
                                set((state) => {
                                    const exists = state.chats.some(
                                        (c) => c.id === currentChatId
                                    );
                                    const newChats = exists
                                        ? state.chats.map((c) =>
                                              c.id === currentChatId
                                                  ? { ...c, messages: state.messages }
                                                  : c
                                          )
                                        : [
                                              {
                                                  id: currentChatId,
                                                  title: defaultTitle,
                                                  messages: state.messages,
                                              },
                                              ...state.chats,
                                          ];

                                    return {
                                        activeChatId: currentChatId,
                                        chats: newChats,
                                    };
                                });
                            }
                            // Append streamed thoughts in real time
                            else if (
                                parsed.type === "thought" &&
                                parsed.content
                            ) {
                                set((state) => {
                                    const updatedMessages = state.messages.map((msg) =>
                                        msg.id === assistantMessageId
                                            ? {
                                                  ...msg,
                                                  thought:
                                                      (msg.thought || "") +
                                                      parsed.content,
                                              }
                                            : msg
                                    );

                                    const currentId = state.activeChatId;
                                    const syncedChats = currentId
                                        ? state.chats.map((c) =>
                                              c.id === currentId
                                                  ? { ...c, messages: updatedMessages }
                                                  : c
                                          )
                                        : state.chats;

                                    return {
                                        messages: updatedMessages,
                                        chats: syncedChats,
                                    };
                                });
                            }
                            // Append streamed chunks to assistant response
                            else if (
                                parsed.type === "chunk" &&
                                parsed.content
                            ) {
                                set((state) => {
                                    const updatedMessages = state.messages.map((msg) =>
                                        msg.id === assistantMessageId
                                            ? {
                                                  ...msg,
                                                  content:
                                                      msg.content +
                                                      parsed.content,
                                              }
                                            : msg
                                    );

                                    const currentId = state.activeChatId;
                                    const syncedChats = currentId
                                        ? state.chats.map((c) =>
                                              c.id === currentId
                                                  ? { ...c, messages: updatedMessages }
                                                  : c
                                          )
                                        : state.chats;

                                    return {
                                        messages: updatedMessages,
                                        chats: syncedChats,
                                    };
                                });
                            }
                        } catch (parseError) {
                            console.warn(
                                "Failed to parse SSE payload chunk:",
                                rawJson,
                                parseError,
                            );
                        }
                    }
                }
            }
        } catch (err: unknown) {
            console.error("Chat execution error:", err);
            const errorMessage =
                err instanceof Error
                    ? err.message
                    : "Failed to communicate with chat backend.";

            // 3. Rollback assistant placeholder if empty and record error
            set((state) => {
                const targetMsg = state.messages.find(
                    (m) => m.id === assistantMessageId,
                );
                const hasContent =
                    targetMsg &&
                    ((targetMsg.content && targetMsg.content.length > 0) ||
                        (targetMsg.thought && targetMsg.thought.length > 0));

                const finalMessages = hasContent
                    ? state.messages
                    : state.messages.filter(
                          (m) => m.id !== assistantMessageId,
                      );

                const currentId = state.activeChatId;
                const syncedChats = currentId
                    ? state.chats.map((c) =>
                          c.id === currentId
                              ? { ...c, messages: finalMessages }
                              : c
                      )
                    : state.chats;

                return {
                    error: errorMessage,
                    messages: finalMessages,
                    chats: syncedChats,
                };
            });
        } finally {
            set({ isLoading: false, sending: false });
        }
    },
}));
