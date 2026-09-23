"use client";
import { useEffect, useRef, useState } from "react";
import AppLayout from "@/components/layout/app-layout";
import TextInput from "@/components/text-input/text-input";
import MarkdownRenderer from "@/components/markdown-renderer";
import { useChatStore } from "@/stores/chat-store";
import { useSessionStore } from "@/stores/session-store";
import {
    Brain,
    ChevronDown,
    FileText,
    Pencil,
    X,
    Check,
    RotateCcw,
    Copy,
} from "lucide-react";

export default function Home() {
    const messages = useChatStore((s) => s.messages);
    const currentStatus = useChatStore((s) => s.currentStatus);
    const isLoading = useChatStore((s) => s.isLoading);
    const lastUserMsg = messages.findLast((m) => m.role === "user");
    const lastAssistantMsg = messages.findLast((m) => m.role === "assistant");

    const editMessage = useChatStore((s) => s.editMessage);
    const retryMessage = useChatStore((s) => s.retryMessage);

    const activeChatId = useSessionStore((s) => s.activeChatId);
    const fetchActiveMount = useSessionStore((s) => s.fetchActiveMount);

    const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
    const [editContent, setEditContent] = useState("");
    const [copiedId, setCopiedId] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Sync the mounted folder chip whenever the active session changes
    useEffect(() => {
        if (activeChatId) {
            void fetchActiveMount(activeChatId);
        }
    }, [activeChatId, fetchActiveMount]);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const handleCopy = (id: string, text: string) => {
        navigator.clipboard.writeText(text);
        setCopiedId(id);
        setTimeout(() => setCopiedId(null), 2000);
    };

    const startEditing = (id: string, text: string) => {
        if (isLoading) return;
        setEditingMessageId(id);
        setEditContent(text);
    };

    const cancelEditing = () => {
        setEditingMessageId(null);
        setEditContent("");
    };

    const submitEdit = (id: string) => {
        if (!editContent.trim()) return;
        void editMessage(id, editContent);
        setEditingMessageId(null);
        setEditContent("");
    };

    return (
        <AppLayout>
            <div className="flex flex-1 flex-col h-full overflow-hidden">
                {messages.length === 0 ? (
                    <div className="flex flex-1 flex-col justify-center">
                        <div className="flex flex-1 items-center justify-center">
                            <h1 className="text-5xl font-semibold" style={{ color: "var(--text)" }}>
                                Where do you want to start?
                            </h1>
                        </div>
                        <TextInput />
                    </div>
                ) : (
                    <div className="flex flex-1 flex-col overflow-hidden">
                        <div className="flex-1 overflow-y-auto px-4 py-6">
                            <div className="mx-auto max-w-4xl space-y-4">
                                {messages.map((msg) => {
                                    const thought = msg.role === "assistant" ? msg.thought : undefined;
                                    const attachments = msg.role === "user" ? msg.attachments ?? [] : [];
                                    const isEditingThis = editingMessageId === msg.id;
                                    const isLastUser = msg.id === lastUserMsg?.id;
                                    const isLastAssistant = msg.id === lastAssistantMsg?.id;
                                    const isCancelled = msg.status === "cancelled";
                                    const isRunning = msg.status === "running";

                                    return (
                                        <div
                                            key={msg.id}
                                            className={`group relative flex flex-col ${
                                                msg.role === "user"
                                                    ? "items-end"
                                                    : "items-start"
                                            }`}
                                        >
                                            {msg.role === "user" && isEditingThis ? (
                                                <div
                                                    className="w-full max-w-[85%] rounded-2xl p-3"
                                                    style={{
                                                        background: "var(--surface-hover)",
                                                        border: "1px solid var(--border)",
                                                    }}
                                                >
                                                    <textarea
                                                        value={editContent}
                                                        onChange={(e) => setEditContent(e.target.value)}
                                                        rows={3}
                                                        className="w-full resize-none rounded-lg bg-transparent p-2 text-sm outline-none text-[var(--text)]"
                                                        autoFocus
                                                    />
                                                    <div className="mt-2 flex justify-end gap-2">
                                                        <button
                                                            type="button"
                                                            onClick={cancelEditing}
                                                            className="flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs text-neutral-400 hover:bg-[var(--surface)]"
                                                        >
                                                            <X size={13} /> Cancel
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => submitEdit(msg.id)}
                                                            className="flex items-center gap-1 rounded-lg px-3 py-1 text-xs font-medium bg-white text-black hover:opacity-90"
                                                        >
                                                            <Check size={13} /> Save & Run
                                                        </button>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="relative max-w-[85%]">
                                                    <div
                                                        className={`rounded-2xl px-4 py-3 text-sm leading-relaxed break-words [overflow-wrap:anywhere] ${
                                                            msg.role === "user"
                                                                ? "whitespace-pre-wrap"
                                                                : ""
                                                        }`}
                                                        style={{
                                                            background:
                                                                msg.role === "user"
                                                                    ? "var(--surface-hover)"
                                                                    : "var(--surface)",
                                                            color: "var(--text)",
                                                            border: "1px solid var(--border)",
                                                        }}
                                                    >
                                                        {/* 1. Thinking Process (if exists) */}
                                                        {msg.role === "assistant" && Boolean(thought) && (
                                                            <details
                                                                open={!msg.content}
                                                                className="mb-3 group rounded-xl border p-2.5 text-xs transition-all"
                                                                style={{
                                                                    borderColor: "var(--border)",
                                                                    background: "var(--surface-hover)",
                                                                }}
                                                            >
                                                                <summary
                                                                    className="flex items-center gap-1.5 cursor-pointer font-medium select-none outline-none"
                                                                    style={{ color: "var(--muted)" }}
                                                                >
                                                                    <Brain size={14} className="shrink-0" />
                                                                    <span>Thinking Process</span>
                                                                    <ChevronDown
                                                                        size={14}
                                                                        className="ml-auto shrink-0 transition-transform duration-200 group-open:rotate-180"
                                                                    />
                                                                </summary>
                                                                <div
                                                                    className="mt-2 pt-2 border-t text-xs whitespace-pre-wrap leading-relaxed opacity-85 max-h-60 overflow-y-auto font-mono"
                                                                    style={{
                                                                        borderColor: "var(--border)",
                                                                        color: "var(--text)",
                                                                    }}
                                                                >
                                                                    {thought}
                                                                </div>
                                                            </details>
                                                        )}

                                                        {/* Uploaded File Badges */}
                                                        {msg.role === "user" && attachments.length > 0 && (
                                                            <div className="mb-2 flex flex-wrap gap-1.5 justify-end">
                                                                {attachments.map((att, idx) => (
                                                                    <span
                                                                        key={`${att.name}-${idx}`}
                                                                        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium shadow-xs"
                                                                        style={{
                                                                            background: "var(--surface)",
                                                                            border: "1px solid var(--border)",
                                                                            color: "var(--text)",
                                                                        }}
                                                                    >
                                                                        <FileText
                                                                            size={12}
                                                                            className="shrink-0 opacity-70"
                                                                        />
                                                                        <span className="max-w-[180px] truncate">
                                                                            {att.name}
                                                                        </span>
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        )}

                                                        {/* 2. Message Markdown Content */}
                                                        {msg.content ? (
                                                            msg.role === "user" ? (
                                                                msg.content
                                                            ) : (
                                                                <MarkdownRenderer content={msg.content} />
                                                            )
                                                        ) : null}

                                                        {/* 3. Status Area */}
                                                        {msg.role === "assistant" && (
                                                            <div className="text-xs text-[var(--muted)]">
                                                                {isRunning && isLoading && (
                                                                    <>
                                                                        {/* Tool call status emit with pulsating animation */}
                                                                        {currentStatus ? (
                                                                            <div className={`flex items-center gap-2 animate-pulse ${msg.content ? "mt-2 pt-1" : ""}`}>
                                                                                <span>{currentStatus}</span>
                                                                            </div>
                                                                        ) : (
                                                                            /* Before text chunks stream: 3 dots bouncy chatting animation flowing left to right */
                                                                            !msg.content && !thought && (
                                                                                <div className="flex items-center gap-1 py-1 text-[var(--muted)]">
                                                                                    <span className="h-1.5 w-1.5 rounded-full bg-current chat-dot chat-dot-1" />
                                                                                    <span className="h-1.5 w-1.5 rounded-full bg-current chat-dot chat-dot-2" />
                                                                                    <span className="h-1.5 w-1.5 rounded-full bg-current chat-dot chat-dot-3" />
                                                                                </div>
                                                                            )
                                                                        )}
                                                                    </>
                                                                )}

                                                                {/* Response cancelled status */}
                                                                {isCancelled && (
                                                                    <div className={`flex items-center gap-1.5 text-xs text-amber-400/90 font-mono ${msg.content ? "mt-2 pt-1" : ""}`}>
                                                                        <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />
                                                                        <span>Response was cancelled</span>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* USER ACTION BAR: Only the latest user prompt can be edited */}
                                                    {msg.role === "user" && !isLoading && (
                                                        <div className="absolute -left-16 top-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            {isLastUser && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => startEditing(msg.id, msg.content)}
                                                                    className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                    title="Edit message"
                                                                >
                                                                    <Pencil size={14} />
                                                                </button>
                                                            )}
                                                            <button
                                                                type="button"
                                                                onClick={() => handleCopy(msg.id, msg.content)}
                                                                className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                title="Copy prompt"
                                                            >
                                                                {copiedId === msg.id ? (
                                                                    <Check size={14} className="text-emerald-400" />
                                                                ) : (
                                                                    <Copy size={14} />
                                                                )}
                                                            </button>
                                                        </div>
                                                    )}

                                                    {/* ASSISTANT ACTION BAR: Retry only on latest uncancelled assistant message */}
                                                    {msg.role === "assistant" && !isLoading && (
                                                        <div className="mt-1 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            {isLastAssistant && !isCancelled && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => void retryMessage(msg.id)}
                                                                    className="flex items-center gap-1 rounded p-1 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                    title="Regenerate response"
                                                                >
                                                                    <RotateCcw size={14} />
                                                                </button>
                                                            )}
                                                            {msg.content && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => handleCopy(msg.id, msg.content)}
                                                                    className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                    title="Copy response"
                                                                >
                                                                    {copiedId === msg.id ? (
                                                                        <Check size={14} className="text-emerald-400" />
                                                                    ) : (
                                                                        <Copy size={14} />
                                                                    )}
                                                                </button>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                                <div ref={messagesEndRef} />
                            </div>
                        </div>
                        <div className="shrink-0 pt-2">
                            <TextInput />
                        </div>
                    </div>
                )}
            </div>
        </AppLayout>
    );
}