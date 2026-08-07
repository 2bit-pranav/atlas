import { create } from "zustand";

export type AttachmentType = "image" | "document";

export interface AttachmentItem {
    id: string;
    file: File;
    name: string;
    type: AttachmentType;
    preview?: string;
}

export interface BrowserProfile {
    id: string;
    name: string;
}

interface TextInputStore {
    text: string;

    attachments: AttachmentItem[];

    selectedProfile: string;

    sending: boolean;

    profileMenuOpen: boolean;

    setText: (text: string) => void;

    setSending: (sending: boolean) => void;

    addAttachment: (attachment: AttachmentItem) => void;

    removeAttachment: (id: string) => void;

    clearAttachments: () => void;

    clearAll: () => void;

    setProfile: (profile: string) => void;

    setProfileMenuOpen: (open: boolean) => void;
}

export const useTextInputStore = create<TextInputStore>((set) => ({
    text: "",

    attachments: [],

    selectedProfile: "default",

    sending: false,

    profileMenuOpen: false,

    setText: (text) =>
        set({
            text,
        }),

    setSending: (sending) =>
        set({
            sending,
        }),

    addAttachment: (attachment) =>
        set((state) => ({
            attachments: [...state.attachments, attachment],
        })),

    removeAttachment: (id) =>
        set((state) => {
            const file = state.attachments.find((a) => a.id === id);

            if (file?.preview) {
                URL.revokeObjectURL(file.preview);
            }

            return {
                attachments: state.attachments.filter((a) => a.id !== id),
            };
        }),

    clearAttachments: () =>
        set((state) => {
            state.attachments.forEach((a) => {
                if (a.preview) {
                    URL.revokeObjectURL(a.preview);
                }
            });

            return {
                attachments: [],
            };
        }),

    clearAll: () =>
        set((state) => {
            state.attachments.forEach((a) => {
                if (a.preview) {
                    URL.revokeObjectURL(a.preview);
                }
            });

            return {
                text: "",

                attachments: [],

                sending: false,
            };
        }),

    setProfile: (profile) =>
        set({
            selectedProfile: profile,
        }),

    setProfileMenuOpen: (open) =>
        set({
            profileMenuOpen: open,
        }),
}));
