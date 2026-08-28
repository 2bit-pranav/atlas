"use client";

import { useRouter } from "next/navigation";
import { ChevronDown, Globe, Plus } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTextInputStore } from "@/stores/text-input-store";

const profiles = [
    {
        id: "default",
        name: "Default Profile",
    },
];

export default function ProfileDropdown() {
    const router = useRouter();
    const selected = useTextInputStore((s) => s.selectedProfile);
    const setProfile = useTextInputStore((s) => s.setProfile);
    const current = profiles.find((p) => p.id === selected) ?? profiles[0];

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                className="flex h-8 items-center gap-2 rounded-lg px-2"
                style={{
                    background: "var(--surface-hover)",
                }}
            >
                <Globe size={15} />
                <span>{current.name}</span>
                <ChevronDown size={15} />
            </DropdownMenuTrigger>

            <DropdownMenuContent side="top" align="start">
                {profiles.map((profile) => (
                    <DropdownMenuItem
                        key={profile.id}
                        onClick={() => setProfile(profile.id)}
                    >
                        {profile.name}
                    </DropdownMenuItem>
                ))}

                <DropdownMenuSeparator />

                <DropdownMenuItem
                    onClick={() => router.push("/browser-profiles")}
                >
                    <Plus size={15} />
                    New Profile
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
