"use client";

import Link from "next/link";
import clsx from "clsx";
import type { LucideIcon } from "lucide-react";

interface SidebarItemProps {
    icon: LucideIcon;
    label: string;
    href?: string;
    collapsed: boolean;
}

export default function SidebarItem({
    icon: Icon,
    label,
    href = "#",
    collapsed,
}: SidebarItemProps) {
    return (
        <Link
            href={href}
            className={clsx(
                "flex h-9 items-center rounded-lg border border-transparent text-sm transition-colors hover:bg-surface-hover",
                collapsed ? "justify-center px-0" : "gap-3 px-3",
            )}
        >
            <Icon size={18} />

            {!collapsed && <span>{label}</span>}
        </Link>
    );
}
