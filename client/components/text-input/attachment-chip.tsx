"use client";

import { FileText, X } from "lucide-react";
import type { AttachmentItem } from "@/stores/text-input-store";

interface Props {
    item: AttachmentItem;
    onDelete: () => void;
}

export default function AttachmentChip({ item, onDelete }: Props) {
    const isImage = item.type === "image";
    const ext = item.name.includes(".")
        ? item.name.split(".").pop()?.toUpperCase()
        : isImage
        ? "IMG"
        : "FILE";

    return (
        <div
            className="group relative flex items-center gap-2.5 rounded-2xl border px-3 py-2 shrink-0 max-w-[220px] transition-all"
            style={{
                background: "var(--surface-hover)",
                borderColor: "var(--border)",
                color: "var(--text)",
            }}
        >
            {isImage && item.preview ? (
                <img
                    src={item.preview}
                    alt={item.name}
                    className="h-9 w-9 rounded-xl object-cover shrink-0 border border-white/10"
                    draggable={false}
                />
            ) : (
                <div
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10"
                    style={{ background: "var(--surface)" }}
                >
                    <FileText
                        size={18}
                        style={{ color: "var(--muted)" }}
                    />
                </div>
            )}

            <div className="flex flex-col min-w-0 flex-1 pr-4">
                <span
                    className="truncate text-xs font-medium leading-tight"
                    title={item.name}
                >
                    {item.name}
                </span>
                <span
                    className="text-[10px] font-mono tracking-wider opacity-60"
                    style={{ color: "var(--muted)" }}
                >
                    {ext}
                </span>
            </div>

            <button
                type="button"
                onClick={onDelete}
                className="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full shadow-md text-white opacity-0 transition-opacity group-hover:opacity-100"
                style={{ background: "#ef4444" }}
                title="Remove attachment"
            >
                <X size={12} />
            </button>
        </div>
    );
}
