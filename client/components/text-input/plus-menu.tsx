"use client";

import { FileIcon, Plus, Sparkles } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface Props {
    onFiles: () => void;
    onSkills: () => void;
}

export default function PlusMenu({ onFiles, onSkills }: Props) {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors"
                style={{
                    background: "var(--surface-hover)",
                }}
            >
                <Plus size={18} />
            </DropdownMenuTrigger>

            <DropdownMenuContent side="top" align="start">
                <DropdownMenuItem onClick={onFiles}>
                    <FileIcon size={16} />
                    Files
                </DropdownMenuItem>

                <DropdownMenuItem onClick={onSkills}>
                    <Sparkles size={16} />
                    Skills
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
