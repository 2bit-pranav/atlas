"use client";

import { useMemo, useRef } from "react";
import AttachmentChip from "./attachment-chip";
import PlusMenu from "./plus-menu";
import ProfileDropdown from "./profile-dropdown";
import TextArea from "./text-area";
import { ArrowUp, Mic } from "lucide-react";
import {
  useTextInputStore,
  type AttachmentItem,
} from "@/stores/text-input-store";
import { useChatStore } from "@/stores/chat-store";

export default function TextInput() {
    const text = useTextInputStore((s) => s.text);
    const attachments = useTextInputStore((s) => s.attachments);
    const setText = useTextInputStore((s) => s.setText);
    const addAttachment = useTextInputStore((s) => s.addAttachment);
    const removeAttachment = useTextInputStore((s) => s.removeAttachment);
    const clearAll = useTextInputStore((s) => s.clearAll);

    const sendMessage = useChatStore((s) => s.sendMessage);
    const sending = useChatStore((s) => s.sending);

    const imageInput = useRef<HTMLInputElement>(null);
    const documentInput = useRef<HTMLInputElement>(null);

    const canSend = useMemo(() => {
        return text.trim().length > 0 && !sending;
    }, [text, sending]);

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
                {/* Header */}
                <div className="mb-3 flex items-center justify-between">
                    <ProfileDropdown />
                </div>

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
                <div className="mt-2 flex items-center">
                    <PlusMenu
                        onImages={() => imageInput.current?.click()}
                        onDocuments={() => documentInput.current?.click()}
                        onSkills={() => console.log("skills")}
                    />

                    <div className="ml-auto flex gap-2">
                        <button
                            disabled
                            title="Coming Soon"
                            className="flex h-9 w-9 items-center justify-center rounded-lg"
                            style={{
                                background: "var(--surface-hover)",
                            }}
                        >
                            <Mic size={18} />
                        </button>

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
