"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
  buildAttachmentItems,
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
    const isLoading = useChatStore((s) => s.isLoading);
    const useCloud = useChatStore((s) => s.useCloud);
    const setUseCloud = useChatStore((s) => s.setUseCloud);
    const thinkingBudget = useChatStore((s) => s.thinkingBudget);
    const setThinkingBudget = useChatStore((s) => s.setThinkingBudget);

    const fileInput = useRef<HTMLInputElement>(null);
    const dragCounter = useRef(0);
    const [isDragging, setIsDragging] = useState(false);
    const [skillNames, setSkillNames] = useState<string[]>([]);
    const [skillIndex, setSkillIndex] = useState(0);

    useEffect(() => {
        void fetch("http://localhost:8001/api/skills/local")
            .then((response) => response.json())
            .then((data) => setSkillNames((data.skills || []).map((skill: { name: string }) => skill.name)))
            .catch(() => setSkillNames([]));
    }, []);

    const skillMatch = text.match(/(?:^|\s)@([A-Za-z0-9._-]*)$/);
    const skillSuggestions = skillMatch
        ? skillNames.filter((name) => name.toLowerCase().startsWith(skillMatch[1].toLowerCase()))
        : [];

    const canSend = useMemo(() => {
        return (text.trim().length > 0 || attachments.length > 0) && !isLoading;
    }, [text, attachments.length, isLoading]);

    const currentThinkingOption = useMemo(() => {
        return (
            THINKING_OPTIONS.find((opt) => opt.value === thinkingBudget) ??
            THINKING_OPTIONS[0]
        );
    }, [thinkingBudget]);

    function handleFiles(files: FileList | null) {
        if (!files || files.length === 0) return;

        const fileArray = Array.from(files);
        const items = buildAttachmentItems(fileArray);
        items.forEach((item) => addAttachment(item));
    }

    function send() {
        if (!canSend) return;

        const prompt = text;
        const attachmentFiles = attachments
            .map((item) => item.file)
            .filter((file): file is File => !!file);

        clearAll();
        void sendMessage(prompt, attachmentFiles);
    }

    function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
        if (skillSuggestions.length > 0 && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter")) {
            e.preventDefault();
            if (e.key === "ArrowDown") setSkillIndex((index) => (index + 1) % skillSuggestions.length);
            if (e.key === "ArrowUp") setSkillIndex((index) => (index - 1 + skillSuggestions.length) % skillSuggestions.length);
            if (e.key === "Enter") {
                const prefix = text.slice(0, text.length - (skillMatch?.[1].length || 0));
                setText(`${prefix}${skillSuggestions[skillIndex]} `);
                setSkillIndex(0);
            }
            return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }

    function handleDragEnter(e: React.DragEvent<HTMLDivElement>) {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current += 1;

        if (e.dataTransfer.types.includes("Files")) {
            setIsDragging(true);
        }
    }

    function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
        e.preventDefault();
        e.stopPropagation();
    }

    function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current -= 1;

        if (dragCounter.current <= 0) {
            dragCounter.current = 0;
            setIsDragging(false);
        }
    }

    function handleDrop(e: React.DragEvent<HTMLDivElement>) {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current = 0;
        setIsDragging(false);
        void handleFiles(e.dataTransfer.files);
    }

    return (
        <>
            <div
                className="mx-auto w-full max-w-4xl rounded-3xl px-4 py-3 mb-5 transition-colors"
                style={{
                    background: isDragging
                        ? "var(--surface-hover)"
                        : "var(--surface)",
                    border: isDragging
                        ? "2px dashed var(--text)"
                        : "2px dashed transparent",
                }}
                onDragEnter={handleDragEnter}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
            >
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

                <div className="relative">
                    {skillSuggestions.length > 0 && (
                        <div className="absolute bottom-full left-0 z-10 mb-2 min-w-40 rounded-lg border p-1 shadow-lg" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                            {skillSuggestions.map((name, index) => (
                                <button key={name} type="button" className="block w-full rounded px-2 py-1 text-left text-xs" style={{ background: index === skillIndex ? "var(--surface-hover)" : "transparent" }} onMouseDown={(event) => event.preventDefault()} onClick={() => { setText(`${text.slice(0, text.length - (skillMatch?.[1].length || 0))}${name} `); setSkillIndex(0); }}>
                                    @{name}
                                </button>
                            ))}
                        </div>
                    )}
                    <TextArea value={text} onChange={setText} onKeyDown={handleKeyDown} />
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-3">
                    <PlusMenu
                        onFiles={() => fileInput.current?.click()}
                    />

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
                ref={fileInput}
                accept="image/*,.pdf,.docx,.xlsx,.xls,.txt,.md,.py,.json,.csv,.log,.html,.xml,.yml,.yaml,.js,.ts"
                type="file"
                onChange={(e) => {
                    void handleFiles(e.target.files);
                    e.target.value = "";
                }}
            />
        </>
    );
}
