import { create } from "zustand";

type Theme = "dark" | "light";

interface UIStore {
    sidebarOpen: boolean;
    terminalOpen: boolean;
    theme: Theme;

    toggleSidebar: () => void;
    toggleTerminal: () => void;
    toggleTheme: () => void;

    setSidebarOpen: (open: boolean) => void;
    setTerminalOpen: (open: boolean) => void;
}

export const useUIStore = create<UIStore>((set) => ({
    sidebarOpen: true,
    terminalOpen: true,
    theme: "dark",

    toggleSidebar: () =>
        set((state) => ({
            sidebarOpen: !state.sidebarOpen,
        })),

    toggleTerminal: () =>
        set((state) => ({
            terminalOpen: !state.terminalOpen,
        })),

    toggleTheme: () =>
        set((state) => ({
            theme: state.theme === "dark" ? "light" : "dark",
        })),

    setSidebarOpen: (open) =>
        set({
            sidebarOpen: open,
        }),

    setTerminalOpen: (open) =>
        set({
            terminalOpen: open,
        }),
}));
