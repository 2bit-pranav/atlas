"use client";

import { useEffect } from "react";
import { useUIStore } from "@/stores/ui-store";

export default function ThemeProvider({
    children,
}: {
    children: React.ReactNode;
}) {
    const theme = useUIStore((s) => s.theme);

    useEffect(() => {
        document.documentElement.classList.toggle("light", theme === "light");
    }, [theme]);

    return children;
}
