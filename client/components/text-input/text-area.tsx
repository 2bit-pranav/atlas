"use client";

import { useEffect, useRef } from "react";
import { Textarea } from "@/components/ui/textarea";

interface Props {
    value: string;
    onChange: (value: string) => void;
}

export default function TextArea({ value, onChange }: Props) {
    const wrapperRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        const textarea = textareaRef.current;

        if (!textarea) return;
        
        textarea.style.height = "0px";
        textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
        
        if (wrapperRef.current) {
            wrapperRef.current.style.height = textarea.style.height;
        }
    }, [value]);

    return (
        <div
            ref={wrapperRef}
            className="relative w-full"
            style={{
                minHeight: 22,
            }}
        >
            <Textarea
                ref={textareaRef}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder="What would you like Atlas to do?"
                className="absolute inset-0 resize-none border-0 bg-transparent p-0 shadow-none focus-visible:ring-0"
                style={{
                    color: "var(--text)",
                    caretColor: "var(--text)",
                    minHeight: 32,
                    background: "transparent",
                }}
            />
        </div>
    );
}
