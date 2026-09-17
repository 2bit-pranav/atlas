"use client";
import { useEffect, useRef, useState } from "react";
import AppLayout from "@/components/layout/app-layout";
import TextInput from "@/components/text-input/text-input";
import MarkdownRenderer from "@/components/markdown-renderer";
import { useChatStore } from "@/stores/chat-store";
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
    const editMessage = useChatStore((s) => s.editMessage);
    const retryMessage = useChatStore((s) => s.retryMessage);

    const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
    const [editContent, setEditContent] = useState("");
    const [copiedId, setCopiedId] = useState<string | null>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);

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

                                    return (
                                        <div
                                            key={msg.id}
                                            className={`group relative flex flex-col ${
                                                msg.role === "user" ? "items-end" : "items-start"
                                            }`}
                                        >
                                            {/* USER EDIT VIEW */}
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
                                                /* REGULAR MESSAGE BUBBLE */
                                                <div className="relative max-w-[85%]">
                                                    <div
                                                        className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                                                            msg.role === "user" ? "whitespace-pre-wrap" : ""
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
                                                        {/* Collapsible Thinking Process */}
                                                        {msg.role === "assistant" && thought && (
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
                                                                        <FileText size={12} className="shrink-0 opacity-70" />
                                                                        <span className="max-w-[180px] truncate">{att.name}</span>
                                                                    </span>
                                                                ))}
                                                            </div>
                                                        )}

                                                        {/* Text Body / Status */}
                                                        {msg.content ? (
                                                            msg.role === "user" ? (
                                                                msg.content
                                                            ) : (
                                                                <MarkdownRenderer content={msg.content} />
                                                            )
                                                        ) : isLoading ? (
                                                            <span className="text-muted text-xs animate-pulse">
                                                                {currentStatus || (thought ? "Reasoning..." : "Thinking...")}
                                                            </span>
                                                        ) : (
                                                            <span className="text-muted text-xs italic opacity-80">
                                                                Response was cancelled
                                                            </span>
                                                        )}
                                                    </div>

                                                    {/* HOVER ACTION BAR: USER (Edit & Copy) */}
                                                    {msg.role === "user" && !isLoading && (
                                                        <div className="absolute -left-16 top-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            <button
                                                                type="button"
                                                                onClick={() => startEditing(msg.id, msg.content)}
                                                                className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                title="Edit message"
                                                            >
                                                                <Pencil size={13} />
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={() => handleCopy(msg.id, msg.content)}
                                                                className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                title="Copy prompt"
                                                            >
                                                                {copiedId === msg.id ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                                                            </button>
                                                        </div>
                                                    )}

                                                    {/* HOVER ACTION BAR: ASSISTANT (Retry & Copy) */}
                                                    {msg.role === "assistant" && msg.content && !isLoading && (
                                                        <div className="mt-1 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            <button
                                                                type="button"
                                                                onClick={() => void retryMessage(msg.id)}
                                                                className="flex items-center gap-1 rounded px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                title="Regenerate alternative response"
                                                            >
                                                                <RotateCcw size={12} /> Retry
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={() => handleCopy(msg.id, msg.content)}
                                                                className="rounded p-1 text-neutral-400 hover:bg-neutral-800 hover:text-white transition-colors"
                                                                title="Copy response"
                                                            >
                                                                {copiedId === msg.id ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                                            </button>
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