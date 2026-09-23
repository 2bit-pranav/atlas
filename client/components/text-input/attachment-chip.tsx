"use client";

import { FileText, Folder, X } from "lucide-react";
import type { AttachmentItem } from "@/stores/text-input-store";

export interface AttachmentChipProps {
    item?: AttachmentItem;
    onDelete?: () => void;
    folderPath?: string;
    onUnmount?: () => void;
}

export default function AttachmentChip({
    item,
    onDelete,
    folderPath,
    onUnmount,
}: AttachmentChipProps) {
    // ── 1. MOUNTED FOLDER VARIANT ──
    if (folderPath) {
        const folderName =
            folderPath.replace(/\\/g, "/").split("/").filter(Boolean).pop() ??
            folderPath;

        return (
            <div
                className="group relative flex items-center gap-2.5 rounded-2xl border px-3 py-2 shrink-0 max-w-[260px] transition-all"
                style={{
                    background: "var(--surface-hover)",
                    borderColor: "var(--border)",
                    color: "var(--text)",
                }}
                title={`${folderPath} (Read-Only Reference)`}
            >
                <div
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10"
                    style={{ background: "var(--surface)" }}
                >
                    <Folder size={16} className="text-amber-400" />
                </div>

                <div className="flex flex-col min-w-0 flex-1">
                    <span
                        className="truncate text-xs font-medium leading-tight"
                        title={folderPath}
                    >
                        {folderName}
                    </span>
                    <span
                        className="text-[10px] font-mono tracking-wider text-amber-400/80"
                    >
                        MOUNTED
                    </span>
                </div>

                <button
                    type="button"
                    onClick={onUnmount}
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-500/90 text-white opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-600 shadow-sm"
                    title="Unmount folder"
                    aria-label="Unmount folder"
                >
                    <X size={12} />
                </button>
            </div>
        );
    }

    // ── 2. FILE / IMAGE ATTACHMENT VARIANT ──
    if (!item) return null;

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
                    <FileText size={18} style={{ color: "var(--muted)" }} />
                </div>
            )}

            <div className="flex flex-col min-w-0 flex-1">
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
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-500/90 text-white opacity-0 transition-opacity group-hover:opacity-100 hover:bg-red-600 shadow-sm"
                title="Remove attachment"
            >
                <X size={12} />
            </button>
        </div>
    );
}