"use client";

import Image from "next/image";

import { FileText, X } from "lucide-react";

import type { AttachmentItem } from "@/stores/text-input-store";

interface Props {
    item: AttachmentItem;
    onDelete: () => void;
}

export default function AttachmentChip({ item, onDelete }: Props) {
    const image = item.type === "image";

    return (
        <div
            className="group relative h-16 w-16 shrink-0 overflow-hidden rounded-xl"
            style={{
                background: "var(--surface-hover)",
            }}
        >
            {image && item.preview ? (
                <Image
                    src={item.preview}
                    alt={item.name}
                    fill
                    unoptimized
                    className="object-cover"
                />
            ) : (
                <div className="flex h-full w-full items-center justify-center">
                    <FileText
                        size={22}
                        style={{
                            color: "var(--muted)",
                        }}
                    />
                </div>
            )}

            <div className="absolute inset-0 flex flex-col justify-between bg-black/65 p-1 opacity-0 transition-opacity group-hover:opacity-100">
                <div className="flex justify-end">
                    <button
                        type="button"
                        onClick={onDelete}
                        className="rounded p-0.5 transition-colors hover:bg-white/15"
                    >
                        <X size={12} />
                    </button>
                </div>

                <p
                    className="line-clamp-2 text-[10px] leading-tight"
                    title={item.name}
                >
                    {item.name}
                </p>
            </div>
        </div>
    );
}
