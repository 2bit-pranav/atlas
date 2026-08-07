"use client";

import ThemeProvider from "@/components/theme-provider";
import Sidebar from "./sidebar";
import TerminalPanel from "./terminal-panel";

interface AppLayoutProps {
    children: React.ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
    return (
        <ThemeProvider>
            <div
                className="flex h-screen overflow-hidden"
                style={{
                    background: "var(--background)",
                }}
            >
                <Sidebar />
                <main className="flex min-w-0 flex-1 flex-col">{children}</main>
                <TerminalPanel />
            </div>
        </ThemeProvider>
    );
}
