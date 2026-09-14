"use client";

import AppLayout from "@/components/layout/app-layout";
import {
    Cpu, Bot, Wrench, Folder, Eye, EyeOff, Save, Check, Info, Sparkles, Server, ShieldCheck
} from "lucide-react";
import { useEffect, useState } from "react";

export interface LocalModelSettings {
    name: string;
    base_url: string;
    temperature: number;
    top_p: number;
    top_k: number;
    context_window: number;
}

export interface CloudModelSettings {
    provider: string;
    name: string;
    api_key: string;
}

export interface ModelSettings {
    local: LocalModelSettings;
    cloud: CloudModelSettings;
}

export interface AgentRuntimeSettings {
    default_mode: string;
    max_tool_iterations: number;
    reflect_on_tool_use: boolean;
    system_prompt_extra: string;
}

export interface ExaToolSettings {
    api_key: string;
    max_results: number;
}

export interface ToolsSettings {
    exa: ExaToolSettings;
}

export interface SystemSettings {
    download_directory: string;
}

export interface SettingsData {
    model: ModelSettings;
    agent_runtime: AgentRuntimeSettings;
    tools: ToolsSettings;
    system: SystemSettings;
}

const API = "/api/settings";

export default function SettingsPage() {
    const [settings, setSettings] = useState<SettingsData | null>(null);
    const [showCloudKey, setShowCloudKey] = useState(false);
    const [showExaKey, setShowExaKey] = useState(false);
    const [localUrlFocused, setLocalUrlFocused] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let mounted = true;
        async function fetchSettings() {
            try {
                const res = await fetch(API);
                if (res.ok && mounted) {
                    const data = await res.json();
                    setSettings(data);
                } else if (mounted) {
                    setError("Failed to load settings.");
                }
            } catch {
                if (mounted) {
                    setError("Could not connect to settings service.");
                }
            }
        }
        void fetchSettings();
        return () => {
            mounted = false;
        };
    }, []);

    async function toggleRevealCloudKey() {
        if (!settings) return;
        if (showCloudKey) {
            setShowCloudKey(false);
        } else {
            if (settings.model.cloud.api_key === "********") {
                try {
                    const res = await fetch(`${API}?reveal=true`);
                    if (res.ok) {
                        const data = await res.json();
                        if (data.model?.cloud?.api_key !== undefined) {
                            updateCloudModel("api_key", data.model.cloud.api_key);
                        }
                    }
                } catch {
                    // Ignore reveal fetch error
                }
            }
            setShowCloudKey(true);
        }
    }

    async function toggleRevealExaKey() {
        if (!settings) return;
        if (showExaKey) {
            setShowExaKey(false);
        } else {
            if (settings.tools.exa.api_key === "********") {
                try {
                    const res = await fetch(`${API}?reveal=true`);
                    if (res.ok) {
                        const data = await res.json();
                        if (data.tools?.exa?.api_key !== undefined) {
                            updateExaTool("api_key", data.tools.exa.api_key);
                        }
                    }
                } catch {
                    // Ignore reveal fetch error
                }
            }
            setShowExaKey(true);
        }
    }

    async function handleSave() {
        if (!settings) return;
        setSaving(true);
        setError(null);
        setSaved(false);
        try {
            const res = await fetch(API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(settings),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.error || "Failed to write settings file.");
            }
            const data = await res.json();
            setSettings(data);
            setSaved(true);
            setTimeout(() => setSaved(false), 3000);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Error saving settings");
        } finally {
            setSaving(false);
        }
    }

    function updateLocalModel<K extends keyof LocalModelSettings>(key: K, value: LocalModelSettings[K]) {
        setSettings((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                model: {
                    ...prev.model,
                    local: {
                        ...prev.model.local,
                        [key]: value,
                    },
                },
            };
        });
    }

    function updateCloudModel<K extends keyof CloudModelSettings>(key: K, value: CloudModelSettings[K]) {
        setSettings((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                model: {
                    ...prev.model,
                    cloud: {
                        ...prev.model.cloud,
                        [key]: value,
                    },
                },
            };
        });
    }

    function updateAgentRuntime<K extends keyof AgentRuntimeSettings>(key: K, value: AgentRuntimeSettings[K]) {
        setSettings((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                agent_runtime: {
                    ...prev.agent_runtime,
                    [key]: value,
                },
            };
        });
    }

    function updateExaTool<K extends keyof ExaToolSettings>(key: K, value: ExaToolSettings[K]) {
        setSettings((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                tools: {
                    ...prev.tools,
                    exa: {
                        ...prev.tools.exa,
                        [key]: value,
                    },
                },
            };
        });
    }

    function updateSystem<K extends keyof SystemSettings>(key: K, value: SystemSettings[K]) {
        setSettings((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                system: {
                    ...prev.system,
                    [key]: value,
                },
            };
        });
    }

    if (!settings && !error) {
        return (
            <AppLayout>
                <div className="flex h-full w-full items-center justify-center p-8">
                    <p className="text-xs opacity-60 animate-pulse">Loading settings...</p>
                </div>
            </AppLayout>
        );
    }

    return (
        <AppLayout>
            <div className="mx-auto h-full w-full max-w-5xl overflow-y-auto p-8">
                <header className="flex items-center justify-between border-b pb-4" style={{ borderColor: "var(--border)" }}>
                    <div>
                        <h1 className="text-xl font-semibold flex items-center gap-2">
                            <Sparkles className="h-5 w-5 opacity-80" />
                            System Settings
                        </h1>
                        <p className="mt-1 text-xs opacity-70">
                            Configure model engines, agent runtime execution, tool integrations, and system paths.
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => void handleSave()}
                            disabled={saving || !settings}
                            className="flex h-9 items-center gap-1.5 rounded-lg px-4 text-xs font-medium shadow-xs transition-opacity disabled:opacity-50"
                            style={{ background: "var(--text)", color: "var(--background)" }}
                        >
                            {saved ? <Check size={14} /> : <Save size={14} />}
                            {saving ? "Saving..." : saved ? "Saved!" : "Save Changes"}
                        </button>
                    </div>
                </header>

                {error && (
                    <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400">
                        {error}
                    </div>
                )}

                {settings && (
                    <div className="mt-6 space-y-6 pb-16">
                        {/* Section 1: Model Settings */}
                        <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                            <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                                <Cpu className="h-4 w-4 opacity-80" />
                                <h2 className="text-sm font-semibold">Model Settings</h2>
                            </div>

                            <div className="space-y-4">
                                {/* Local Model Execution */}
                                <div className="rounded-lg border p-4 space-y-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                    <h3 className="text-xs font-medium flex items-center justify-between">
                                        <span className="flex items-center gap-1.5">
                                            <Server size={13} className="opacity-70" />
                                            Local Model
                                        </span>
                                        <span className="rounded-full px-2 py-0.5 text-[10px] uppercase font-mono tracking-wider border opacity-70" style={{ borderColor: "var(--border)" }}>llama-server</span>
                                    </h3>

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Model Name</label>
                                            <input
                                                type="text"
                                                value={settings.model.local.name}
                                                onChange={(e) => updateLocalModel("name", e.target.value)}
                                                placeholder="gemma-4-E2B_q4_0-it.gguf"
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                        </div>

                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Server Base URL</label>
                                            <input
                                                type="text"
                                                value={settings.model.local.base_url}
                                                onFocus={() => setLocalUrlFocused(true)}
                                                onBlur={() => setLocalUrlFocused(false)}
                                                onChange={(e) => updateLocalModel("base_url", e.target.value)}
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none transition-colors focus:border-white/40 font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                            {localUrlFocused && (
                                                <p className="mt-1 flex items-center gap-1 text-[10px] text-amber-400/90 font-mono">
                                                    <Info size={11} />
                                                    OpenAI-compatible endpoint (e.g. http://127.0.0.1:8000/v1)
                                                </p>
                                            )}
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Temperature</label>
                                            <input
                                                type="number"
                                                step="0.05"
                                                min="0"
                                                max="2"
                                                value={settings.model.local.temperature}
                                                onChange={(e) => updateLocalModel("temperature", parseFloat(e.target.value) || 0)}
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                        </div>

                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Top-P Sampling</label>
                                            <input
                                                type="number"
                                                step="0.05"
                                                min="0"
                                                max="1"
                                                value={settings.model.local.top_p}
                                                onChange={(e) => updateLocalModel("top_p", parseFloat(e.target.value) || 0)}
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                        </div>

                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Top-K Sampling</label>
                                            <input
                                                type="number"
                                                min="1"
                                                max="100"
                                                value={settings.model.local.top_k}
                                                onChange={(e) => updateLocalModel("top_k", parseInt(e.target.value) || 0)}
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                        </div>

                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Context Window</label>
                                            <input
                                                type="number"
                                                step="1024"
                                                min="1024"
                                                value={settings.model.local.context_window}
                                                onChange={(e) => updateLocalModel("context_window", parseInt(e.target.value) || 8192)}
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                        </div>
                                    </div>
                                </div>

                                {/* Cloud Model Provider */}
                                <div className="rounded-lg border p-4 space-y-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                    <h3 className="text-xs font-medium flex items-center justify-between">
                                        <span className="flex items-center gap-1.5">
                                            <ShieldCheck size={13} className="opacity-70" />
                                            Cloud Model
                                        </span>
                                        <span className="rounded-full px-2 py-0.5 text-[10px] uppercase font-mono tracking-wider border opacity-70" style={{ borderColor: "var(--border)" }}>API Key Encrypted</span>
                                    </h3>

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Cloud Provider</label>
                                            <select
                                                value={settings.model.cloud.provider}
                                                onChange={(e) => updateCloudModel("provider", e.target.value)}
                                                className="h-9 w-full rounded-lg border bg-[var(--surface)] px-2.5 text-xs outline-none"
                                                style={{ borderColor: "var(--border)" }}
                                            >
                                                <option value="google">Google Gemini</option>
                                                <option value="openai">ChatGPT (OpenAI)</option>
                                                <option value="anthropic">Claude (Anthropic)</option>
                                            </select>
                                        </div>

                                        <div>
                                            <label className="block text-xs font-medium mb-1 opacity-80">Model ID</label>
                                            <input
                                                type="text"
                                                value={settings.model.cloud.name}
                                                onChange={(e) => updateCloudModel("name", e.target.value)}
                                                placeholder="gemini-3.5-flash-lite"
                                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">API Key</label>
                                        <div className="relative flex items-center">
                                            <input
                                                type={showCloudKey ? "text" : "password"}
                                                value={settings.model.cloud.api_key}
                                                onChange={(e) => updateCloudModel("api_key", e.target.value)}
                                                placeholder="Enter Cloud API Key..."
                                                className="h-9 w-full rounded-lg border bg-transparent pl-3 pr-9 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                            <button
                                                type="button"
                                                onClick={() => void toggleRevealCloudKey()}
                                                title={showCloudKey ? "Mask API Key" : "Reveal API Key"}
                                                className="absolute right-2 p-1 opacity-60 hover:opacity-100 transition-opacity"
                                            >
                                                {showCloudKey ? <EyeOff size={14} /> : <Eye size={14} />}
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </section>

                        {/* Section 2: Agent Runtime Settings */}
                        <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                            <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                                <Bot className="h-4 w-4 opacity-80" />
                                <h2 className="text-sm font-semibold">Agent Runtime</h2>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start mb-4">
                                <div className="space-y-3">
                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Default Model Mode</label>
                                        <select
                                            value={settings.agent_runtime.default_mode}
                                            onChange={(e) => updateAgentRuntime("default_mode", e.target.value)}
                                            className="h-9 w-full rounded-lg border bg-[var(--surface)] px-2.5 text-xs outline-none"
                                            style={{ borderColor: "var(--border)" }}
                                        >
                                            <option value="local">Local Model (llama-server)</option>
                                            <option value="cloud">Cloud Provider API</option>
                                        </select>
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Max Tool Iterations</label>
                                        <input
                                            type="number"
                                            min="1"
                                            max="20"
                                            value={settings.agent_runtime.max_tool_iterations}
                                            onChange={(e) => updateAgentRuntime("max_tool_iterations", parseInt(e.target.value) || 5)}
                                            className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                    </div>
                                </div>

                                <div className="space-y-3">
                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Post-Tool Reflection</label>
                                        <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                            <span className="text-xs font-medium">Enable reflective reasoning after tool calls</span>
                                            <input
                                                type="checkbox"
                                                checked={settings.agent_runtime.reflect_on_tool_use}
                                                onChange={(e) => updateAgentRuntime("reflect_on_tool_use", e.target.checked)}
                                                className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Custom System Prompt</label>
                                <textarea
                                    value={settings.agent_runtime.system_prompt_extra}
                                    onChange={(e) => updateAgentRuntime("system_prompt_extra", e.target.value)}
                                    placeholder="Global user instructions injected into main orchestrator system message..."
                                    rows={3}
                                    className="w-full rounded-lg border bg-transparent p-3 text-xs outline-none font-mono focus:border-white/40 resize-y"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                        </section>

                        {/* Section 3: Tools Settings */}
                        <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                            <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                                <Wrench className="h-4 w-4 opacity-80" />
                                <h2 className="text-sm font-semibold">Tools & Integrations</h2>
                            </div>

                            <div className="rounded-lg border p-4 space-y-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <h3 className="text-xs font-medium flex items-center justify-between">
                                    <span>Exa Web Search</span>
                                    <span className="rounded-full px-2 py-0.5 text-[10px] uppercase font-mono tracking-wider border opacity-70" style={{ borderColor: "var(--border)" }}>Search API</span>
                                </h3>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-start">
                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Exa Search API Key</label>
                                        <div className="relative flex items-center">
                                            <input
                                                type={showExaKey ? "text" : "password"}
                                                value={settings.tools.exa.api_key}
                                                onChange={(e) => updateExaTool("api_key", e.target.value)}
                                                placeholder="exa-..."
                                                className="h-9 w-full rounded-lg border bg-transparent pl-3 pr-9 text-xs outline-none font-mono"
                                                style={{ borderColor: "var(--border)" }}
                                            />
                                            <button
                                                type="button"
                                                onClick={() => void toggleRevealExaKey()}
                                                title={showExaKey ? "Mask API Key" : "Reveal API Key"}
                                                className="absolute right-2 p-1 opacity-60 hover:opacity-100 transition-opacity"
                                            >
                                                {showExaKey ? <EyeOff size={14} /> : <Eye size={14} />}
                                            </button>
                                        </div>
                                        <p className="mt-1 text-[10px] opacity-60 font-mono">
                                            Safely stored with Windows DPAPI encryption (win32crypt).
                                        </p>
                                    </div>

                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Max Search Results</label>
                                        <input
                                            type="number"
                                            min="1"
                                            max="50"
                                            value={settings.tools.exa.max_results}
                                            onChange={(e) => updateExaTool("max_results", parseInt(e.target.value) || 5)}
                                            className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                    </div>
                                </div>
                            </div>
                        </section>

                        {/* Section 4: System Settings */}
                        <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                            <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                                <Folder className="h-4 w-4 opacity-80" />
                                <h2 className="text-sm font-semibold">System Settings</h2>
                            </div>

                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Download Directory Path</label>
                                <input
                                    type="text"
                                    value={settings.system.download_directory}
                                    onChange={(e) => updateSystem("download_directory", e.target.value)}
                                    placeholder="Absolute path (e.g. C:\Users\...\Downloads). Defaults to user Downloads folder if empty."
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                        </section>
                    </div>
                )}
            </div>
        </AppLayout>
    );
}