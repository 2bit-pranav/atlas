"use client";

import { useEffect, useRef } from "react";
import AppLayout from "@/components/layout/app-layout";
import TextInput from "@/components/text-input/text-input";
import MarkdownRenderer from "@/components/markdown-renderer";
import { useChatStore } from "@/stores/chat-store";
import { Brain, ChevronDown, FileText } from "lucide-react";

export default function Home() {
    const messages = useChatStore((s) => s.messages);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // auto scroll to latest message chunk
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    return (
        <AppLayout>
            <div className="flex flex-1 flex-col h-full overflow-hidden">
                {messages.length === 0 ? (
                    <div className="flex flex-1 flex-col justify-center">
                        <div className="flex flex-1 items-center justify-center">
                            <h1
                                className="text-5xl font-semibold"
                                style={{ color: "var(--text)" }}
                            >
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
                                    const thought =
                                        msg.role === "assistant"
                                            ? msg.thought
                                            : undefined;
                                    const attachments =
                                        msg.role === "user"
                                            ? msg.attachments ?? []
                                            : [];

                                    return (
                                        <div
                                            key={msg.id}
                                            className={`flex flex-col ${
                                                msg.role === "user"
                                                    ? "items-end"
                                                    : "items-start"
                                            }`}
                                        >
                                            <div
                                                className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
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
                                                {/* Collapsible Reasoning Process for Assistant */}
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

                                                {/* User compact attachment pills */}
                                                {msg.role === "user" && attachments.length > 0 && (
                                                    <div className="mb-2 flex flex-wrap gap-1.5 justify-end">
                                                        {attachments.map((attachment, idx) => (
                                                            <span
                                                                key={`${attachment.name}-${idx}`}
                                                                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium shadow-xs"
                                                                style={{
                                                                    background: "var(--surface)",
                                                                    border: "1px solid var(--border)",
                                                                    color: "var(--text)",
                                                                }}
                                                            >
                                                                <FileText size={12} className="shrink-0 opacity-70" />
                                                                <span className="max-w-[180px] truncate">{attachment.name}</span>
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Actual Response Content */}
                                                {msg.content ? (
                                                    msg.role === "user" ? (
                                                        msg.content
                                                    ) : (
                                                        <MarkdownRenderer content={msg.content} />
                                                    )
                                                ) : thought ? (
                                                    <span className="text-muted text-xs animate-pulse">
                                                        Formulating response...
                                                    </span>
                                                ) : (
                                                    <span className="text-muted animate-pulse">
                                                        Atlas is thinking...
                                                    </span>
                                                )}
                                            </div>
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
