"use client";

import AppLayout from "@/components/layout/app-layout";
import { Mail, ShieldCheck, ExternalLink, RefreshCw, ChevronDown } from "lucide-react";
import { useState } from "react";

export default function IntegrationsPage() {
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState("");
    const [expanded, setExpanded] = useState(false);
    const [connected, setConnected] = useState(() => {
    
    if (typeof window === "undefined") return false;
        return localStorage.getItem("atlas_gmail_connected") === "true";
    });

    const [email, setEmail] = useState(() => {
        if (typeof window === "undefined") return "";
        return localStorage.getItem("atlas_gmail_email") ?? "";
    });

    function toggleConnection() {
        setSaving(true);
        const nextState = !connected;
        setConnected(nextState);
        localStorage.setItem("atlas_gmail_connected", String(nextState));
        if (email) localStorage.setItem("atlas_gmail_email", email);
        setMessage(nextState ? "Gmail connected successfully." : "Gmail account disconnected.");
        setTimeout(() => {
            setSaving(false);
            setMessage("");
        }, 2000);
    }

    const badgeClass = connected
        ? "rounded-full px-2.5 py-0.5 text-[11px] font-medium border bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
        : "rounded-full px-2.5 py-0.5 text-[11px] font-medium border bg-zinc-500/10 text-zinc-400 border-zinc-500/20";

    const btnStyle = connected
        ? { background: "var(--surface-hover)", color: "var(--text)", border: "1px solid var(--border)" }
        : { background: "var(--text)", color: "var(--background)" };

    return (
        <AppLayout>
            <div className="mx-auto h-full w-full max-w-5xl overflow-y-auto p-8">
                <header className="border-b pb-4" style={{ borderColor: "var(--border)" }}>
                    <h1 className="text-xl font-semibold flex items-center gap-2">
                        <Mail className="h-5 w-5 opacity-80" />
                        Integrations & External Services
                    </h1>
                    <p className="mt-1 text-xs opacity-70">
                        Connect external service providers to enable email automation and OAuth actions.
                    </p>
                </header>

                <div className="mt-6">
                    <h2 className="text-xs font-medium opacity-80 mb-3">Available Integrations (1)</h2>

                    {/* Collapsible Gmail Card */}
                    <div
                        className="rounded-xl border shadow-xs transition-all overflow-hidden"
                        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                    >
                        {/* Card Header / Closed Bar */}
                        <div
                            onClick={() => setExpanded(!expanded)}
                            className="flex items-center justify-between p-4 cursor-pointer hover:bg-[var(--surface-hover)] transition-colors select-none"
                        >
                            <div className="flex items-center gap-3">
                                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 shrink-0">
                                    <Mail size={20} />
                                </div>
                                <div className="flex items-center gap-2.5">
                                    <h3 className="text-sm font-semibold">Gmail Integration</h3>
                                    <span className={badgeClass}>
                                        {connected ? "Connected" : "Disconnected"}
                                    </span>
                                </div>
                            </div>

                            <button
                                type="button"
                                className="p-1 rounded-lg opacity-60 hover:opacity-100 transition-transform duration-200"
                                style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
                                title={expanded ? "Collapse details" : "Expand details"}
                            >
                                <ChevronDown size={18} />
                            </button>
                        </div>

                        {/* Collapsible Details Body */}
                        {expanded && (
                            <div className="border-t p-5 space-y-4" style={{ borderColor: "var(--border)" }}>
                                <p className="text-xs opacity-80 leading-relaxed">
                                    Connect your Gmail account to enable Atlas to search your inbox, read thread contexts, draft responses, and send messages on your behalf with permission.
                                </p>

                                {message && (
                                    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs text-emerald-400">
                                        {message}
                                    </div>
                                )}

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Associated Account Email</label>
                                        <input
                                            type="email"
                                            value={email}
                                            onChange={(e) => {
                                                setEmail(e.target.value);
                                                localStorage.setItem("atlas_gmail_email", e.target.value);
                                            }}
                                            placeholder="user@gmail.com or company@domain.com"
                                            className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Granted Permission Scopes</label>
                                        <div className="flex items-center gap-1.5 pt-1">
                                            <span className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] border font-mono opacity-80" style={{ borderColor: "var(--border)" }}>
                                                <ShieldCheck size={12} className="text-emerald-400" /> gmail.readonly
                                            </span>
                                            <span className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] border font-mono opacity-80" style={{ borderColor: "var(--border)" }}>
                                                <ShieldCheck size={12} className="text-emerald-400" /> gmail.compose
                                            </span>
                                            <span className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] border font-mono opacity-80" style={{ borderColor: "var(--border)" }}>
                                                <ShieldCheck size={12} className="text-emerald-400" /> gmail.send
                                            </span>
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between pt-3 border-t text-xs" style={{ borderColor: "var(--border)" }}>
                                    <span className="opacity-60 text-[11px]">OAuth 2.0 Credentials: Managed locally via Atlas Auth Proxy</span>
                                    <div className="flex items-center gap-3">
                                        <a
                                            href="https://developers.google.com/gmail/api"
                                            target="_blank"
                                            rel="noreferrer"
                                            className="flex items-center gap-1 opacity-70 hover:opacity-100 hover:underline text-[11px]"
                                        >
                                            Gmail API Docs <ExternalLink size={11} />
                                        </a>
                                        <button
                                            type="button"
                                            onClick={toggleConnection}
                                            disabled={saving}
                                            className="flex h-9 items-center gap-1.5 rounded-lg px-4 text-xs font-medium transition-opacity disabled:opacity-50"
                                            style={btnStyle}
                                        >
                                            {saving && <RefreshCw size={13} className="animate-spin" />}
                                            {connected ? "Disconnect" : "Connect Gmail"}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </AppLayout>
    );
}