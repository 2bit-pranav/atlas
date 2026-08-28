"use client";

import { useMemo, useRef } from "react";
import AttachmentChip from "./attachment-chip";
import PlusMenu from "./plus-menu";
import TextArea from "./text-area";
import { ArrowUp, ChevronDown, Check } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useTextInputStore,
  type AttachmentItem,
} from "@/stores/text-input-store";
import { useChatStore } from "@/stores/chat-store";

const THINKING_OPTIONS = [
    { label: "Off", value: 0 },
    { label: "Low (512 tokens)", value: 512 },
    { label: "Medium (2048 tokens)", value: 2048 },
    { label: "High (8192 tokens)", value: 8192 },
];

export default function TextInput() {
    const text = useTextInputStore((s) => s.text);
    const attachments = useTextInputStore((s) => s.attachments);
    const setText = useTextInputStore((s) => s.setText);
    const addAttachment = useTextInputStore((s) => s.addAttachment);
    const removeAttachment = useTextInputStore((s) => s.removeAttachment);
    const clearAll = useTextInputStore((s) => s.clearAll);

    const sendMessage = useChatStore((s) => s.sendMessage);
    const sending = useChatStore((s) => s.sending);
    const useCloud = useChatStore((s) => s.useCloud);
    const setUseCloud = useChatStore((s) => s.setUseCloud);
    const thinkingBudget = useChatStore((s) => s.thinkingBudget);
    const setThinkingBudget = useChatStore((s) => s.setThinkingBudget);

    const imageInput = useRef<HTMLInputElement>(null);
    const documentInput = useRef<HTMLInputElement>(null);

    const canSend = useMemo(() => {
        return text.trim().length > 0 && !sending;
    }, [text, sending]);

    const currentThinkingOption = useMemo(() => {
        return (
            THINKING_OPTIONS.find((opt) => opt.value === thinkingBudget) ??
            THINKING_OPTIONS[0]
        );
    }, [thinkingBudget]);

    function handleFiles(files: FileList | null) {
        if (!files) return;

        Array.from(files).forEach((file) => {
            const attachment: AttachmentItem = {
                id: crypto.randomUUID(),
                file,
                name: file.name,
                type: file.type.startsWith("image") ? "image" : "document",
                preview: file.type.startsWith("image")
                    ? URL.createObjectURL(file)
                    : undefined,
            };

            addAttachment(attachment);
        });
    }

    function send() {
        if (!canSend) return;
        const prompt = text;
        clearAll();
        sendMessage(prompt);
    }

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }

    return (
        <>
            <div
                className="mx-auto w-full max-w-4xl rounded-3xl px-4 py-3 mb-5"
                style={{
                    background: "var(--surface)",
                }}
            >
                {/* Attachments */}
                {attachments.length > 0 && (
                    <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
                        {attachments.map((attachment) => (
                            <AttachmentChip
                                key={attachment.id}
                                item={attachment}
                                onDelete={() => removeAttachment(attachment.id)}
                            />
                        ))}
                    </div>
                )}

                {/* Editor */}
                <div className="relative">
                    <TextArea value={text} onChange={setText} onKeyDown={handleKeyDown} />
                </div>

                {/* Toolbar */}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                    <PlusMenu
                        onImages={() => imageInput.current?.click()}
                        onDocuments={() => documentInput.current?.click()}
                        onSkills={() => console.log("skills")}
                    />

                    {/* Thinking Dropdown with Label */}
                    <div className="flex items-center gap-1.5">
                        <span
                            className="text-xs font-medium select-none"
                            style={{ color: "var(--muted)" }}
                        >
                            Thinking
                        </span>

                        <DropdownMenu>
                            <DropdownMenuTrigger
                                disabled={useCloud}
                                title={
                                    useCloud
                                        ? "Thinking budget disabled for cloud model"
                                        : "Select thinking budget"
                                }
                                className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs outline-none transition-all"
                                style={{
                                    background: "var(--surface-hover)",
                                    color: "var(--text)",
                                    opacity: useCloud ? 0.5 : 1,
                                    cursor: useCloud ? "not-allowed" : "pointer",
                                }}
                            >
                                <span className="text-xs font-normal">
                                    {currentThinkingOption.label}
                                </span>
                                <ChevronDown
                                    size={14}
                                    className="shrink-0"
                                    style={{ color: "var(--muted)" }}
                                />
                            </DropdownMenuTrigger>

                            <DropdownMenuContent side="top" align="start" className="min-w-[190px]">
                                {THINKING_OPTIONS.map((opt) => (
                                    <DropdownMenuItem
                                        key={opt.value}
                                        onClick={() => setThinkingBudget(opt.value)}
                                        className="flex items-center justify-between text-xs font-normal cursor-pointer"
                                    >
                                        <span className="text-xs font-normal">
                                            {opt.label}
                                        </span>
                                        {thinkingBudget === opt.value && (
                                            <Check size={13} className="ml-2 shrink-0" />
                                        )}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>

                    {/* Use Cloud Switch Toggle */}
                    <div className="flex items-center gap-2">
                        <label
                            className="flex items-center gap-2 text-xs font-medium cursor-pointer select-none"
                            style={{ color: "var(--text)" }}
                        >
                            <span>Use Cloud</span>
                            <button
                                type="button"
                                role="switch"
                                aria-checked={useCloud}
                                onClick={() => setUseCloud(!useCloud)}
                                className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none"
                                style={{
                                    background: useCloud ? "var(--text)" : "var(--surface-hover)",
                                    border: "1px solid var(--border)",
                                }}
                            >
                                <span
                                    className="pointer-events-none inline-block h-4 w-4 transform rounded-full shadow transition duration-200 ease-in-out"
                                    style={{
                                        background: useCloud ? "var(--background)" : "var(--muted)",
                                        transform: useCloud ? "translateX(16px)" : "translateX(2px)",
                                        marginTop: "1px",
                                    }}
                                />
                            </button>
                        </label>
                    </div>

                    <div className="ml-auto flex gap-2">
                        <button
                            disabled={!canSend}
                            onClick={send}
                            className="flex h-9 w-9 items-center justify-center rounded-lg"
                            style={{
                                background: canSend
                                    ? "white"
                                    : "var(--surface-hover)",

                                color: canSend ? "#111" : "var(--muted)",
                            }}
                        >
                            <ArrowUp size={18} />
                        </button>
                    </div>
                </div>
            </div>

            <input
                hidden
                multiple
                ref={imageInput}
                accept="image/png,image/jpeg,image/webp"
                type="file"
                onChange={(e) => handleFiles(e.target.files)}
            />

            <input
                hidden
                multiple
                ref={documentInput}
                accept=".pdf,.txt"
                type="file"
                onChange={(e) => handleFiles(e.target.files)}
            />
        </>
    );
}
