"use client";

import { Paperclip } from "lucide-react";

interface Props {
    onFiles: () => void;
}

export default function PlusMenu({ onFiles }: Props) {
    return (
        <button
            type="button"
            onClick={onFiles}
            title="Attach files"
            aria-label="Attach files"
            className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:opacity-80"
            style={{ background: "var(--surface-hover)" }}
        >
            <Paperclip size={18} />
        </button>
    );
}
