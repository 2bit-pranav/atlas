"use client";

import { FileText, ImageIcon, Plus, Sparkles } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface Props {
    onImages: () => void;
    onDocuments: () => void;
    onSkills: () => void;
}

export default function PlusMenu({
    onImages,
    onDocuments,
    onSkills,
}: Props) {
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
                <DropdownMenuItem onClick={onImages}>
                    <ImageIcon size={16} />
                    Images
                </DropdownMenuItem>

                <DropdownMenuItem onClick={onDocuments}>
                    <FileText size={16} />
                    Documents
                </DropdownMenuItem>

                <DropdownMenuItem onClick={onSkills}>
                    <Sparkles size={16} />
                    Skills
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
