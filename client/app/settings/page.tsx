"use client";

import AppLayout from "@/components/layout/app-layout";
import {
    Cpu, Search, Globe, Bot, Database, Eye, EyeOff, Save, Check, RotateCcw, Info, Sparkles
} from "lucide-react";
import { useEffect, useState } from "react";

interface SettingsData {
    local_model_url: string;
    local_model_name: string;
    cloud_provider: string;
    cloud_model_name: string;
    cloud_api_key: string;
    exa_api_key: string;
    web_search_enabled: boolean;
    web_search_max_results: number;
    browser_headless: boolean;
    browser_width: number;
    browser_height: number;
    browser_max_steps: number;
    browser_max_failures: number;
    browser_enable_planning: boolean;
    browser_wait_strategy: string;
    browser_page_load_timeout: number;
    browser_use_vision: boolean;
    agent_max_tool_iterations: number;
    agent_reflect_on_tool_use: boolean;
    agent_stream_thoughts: boolean;
    agent_thinking_budget: string;
    session_persist: boolean;
    session_max_count: number;
}

const DEFAULT_SETTINGS: SettingsData = {
    local_model_url: "http://127.0.0.1:8000/v1",
    local_model_name: "gemma-4-E2B_q4_0-it.gguf",
    cloud_provider: "google",
    cloud_model_name: "gemini-3.5-flash-lite",
    cloud_api_key: "",
    exa_api_key: "",
    web_search_enabled: true,
    web_search_max_results: 5,
    browser_headless: false,
    browser_width: 1280,
    browser_height: 720,
    browser_max_steps: 10,
    browser_max_failures: 2,
    browser_enable_planning: true,
    browser_wait_strategy: "smart",
    browser_page_load_timeout: 30,
    browser_use_vision: false,
    agent_max_tool_iterations: 5,
    agent_reflect_on_tool_use: true,
    agent_stream_thoughts: true,
    agent_thinking_budget: "off",
    session_persist: true,
    session_max_count: 50,
};

const API = "/api/settings";

export default function SettingsPage() {
    const [settings, setSettings] = useState<SettingsData>(DEFAULT_SETTINGS);
    const [showCloudKey, setShowCloudKey] = useState(false);
    const [showExaKey, setShowExaKey] = useState(false);
    const [localUrlFocused, setLocalUrlFocused] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        async function fetchSettings() {
            try {
                const res = await fetch(API);
                if (res.ok) {
                    const data = await res.json();
                    setSettings((prev) => ({ ...prev, ...data }));
                }
            } catch (err) {
                console.error("Failed to load settings:", err);
            }
        }
        void fetchSettings();
    }, []);

    async function handleSave() {
        setSaving(true);
        setError(null);
        setSaved(false);
        try {
            const res = await fetch(API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(settings),
            });
            if (!res.ok) throw new Error("Failed to write settings file.");
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

    function updateField<K extends keyof SettingsData>(key: K, value: SettingsData[K]) {
        setSettings((prev) => ({ ...prev, [key]: value }));
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
                            Configure model engines, browser runtimes, web search, and agent execution policies.
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => setSettings(DEFAULT_SETTINGS)}
                            className="flex h-9 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors hover:bg-[var(--surface-hover)]"
                            style={{ borderColor: "var(--border)" }}
                        >
                            <RotateCcw size={13} />
                            Reset Defaults
                        </button>
                        <button
                            type="button"
                            onClick={() => void handleSave()}
                            disabled={saving}
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

                <div className="mt-6 space-y-6 pb-16">
                    {/* Section 1: Inference Engine */}
                    <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                        <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                            <Cpu className="h-4 w-4 opacity-80" />
                            <h2 className="text-sm font-semibold">Inference Engine</h2>
                        </div>

                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                            {/* Local Model Card */}
                            <div className="rounded-lg border p-4 space-y-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <h3 className="text-xs font-medium flex items-center justify-between">
                                    <span>Local Model Execution</span>
                                    <span className="rounded-full px-2 py-0.5 text-[10px] uppercase font-mono tracking-wider border opacity-70" style={{ borderColor: "var(--border)" }}>Ollama / LM Studio</span>
                                </h3>

                                <div>
                                    <label className="block text-xs font-medium mb-1 opacity-80">Base URL Endpoint</label>
                                    <input
                                        type="text"
                                        value={settings.local_model_url}
                                        onFocus={() => setLocalUrlFocused(true)}
                                        onBlur={() => setLocalUrlFocused(false)}
                                        onChange={(e) => updateField("local_model_url", e.target.value)}
                                        className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none transition-colors focus:border-white/40 font-mono"
                                        style={{ borderColor: "var(--border)" }}
                                    />
                                    {localUrlFocused && (
                                        <p className="mt-1 flex items-center gap-1 text-[10px] text-amber-400/90 font-mono">
                                            <Info size={11} />
                                            Must be OpenAI-compatible endpoint format (e.g. http://127.0.0.1:8000/v1)
                                        </p>
                                    )}
                                </div>

                                <div>
                                    <label className="block text-xs font-medium mb-1 opacity-80">Model Name / Quantization</label>
                                    <input
                                        type="text"
                                        value={settings.local_model_name}
                                        onChange={(e) => updateField("local_model_name", e.target.value)}
                                        placeholder="gemma-4-E2B_q4_0-it.gguf"
                                        className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                        style={{ borderColor: "var(--border)" }}
                                    />
                                </div>
                            </div>

                            {/* Cloud Model Card */}
                            <div className="rounded-lg border p-4 space-y-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <h3 className="text-xs font-medium flex items-center justify-between">
                                    <span>Cloud API Provider</span>
                                    <span className="rounded-full px-2 py-0.5 text-[10px] uppercase font-mono tracking-wider border opacity-70" style={{ borderColor: "var(--border)" }}>High Accuracy</span>
                                </h3>

                                <div className="grid grid-cols-2 gap-2.5">
                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Provider</label>
                                        <select
                                            value={settings.cloud_provider}
                                            onChange={(e) => updateField("cloud_provider", e.target.value)}
                                            className="h-9 w-full rounded-lg border bg-[var(--surface)] px-2.5 text-xs outline-none"
                                            style={{ borderColor: "var(--border)" }}
                                        >
                                            <option value="google">Google Gemini</option>
                                            <option value="openai">ChatGPT (OpenAI)</option>
                                            <option value="anthropic">Claude (Anthropic)</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-medium mb-1 opacity-80">Model Target</label>
                                        <input
                                            type="text"
                                            value={settings.cloud_model_name}
                                            onChange={(e) => updateField("cloud_model_name", e.target.value)}
                                            className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none font-mono"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-xs font-medium mb-1 opacity-80">API Key Secret</label>
                                    <div className="relative flex items-center">
                                        <input
                                            type={showCloudKey ? "text" : "password"}
                                            value={settings.cloud_api_key}
                                            onChange={(e) => updateField("cloud_api_key", e.target.value)}
                                            placeholder="AIzaSy... or sk-..."
                                            className="h-9 w-full rounded-lg border bg-transparent pl-3 pr-9 text-xs outline-none font-mono"
                                            style={{ borderColor: "var(--border)" }}
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowCloudKey(!showCloudKey)}
                                            className="absolute right-2 p-1 opacity-60 hover:opacity-100"
                                        >
                                            {showCloudKey ? <EyeOff size={14} /> : <Eye size={14} />}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* Section 2: Web Research */}
                    <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                        <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                            <Search className="h-4 w-4 opacity-80" />
                            <h2 className="text-sm font-semibold">Web Research & Retrieval</h2>
                        </div>

                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 items-start">
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">EXA / Web Search API Key</label>
                                <div className="relative flex items-center">
                                    <input
                                        type={showExaKey ? "text" : "password"}
                                        value={settings.exa_api_key}
                                        onChange={(e) => updateField("exa_api_key", e.target.value)}
                                        placeholder="exa-..."
                                        className="h-9 w-full rounded-lg border bg-transparent pl-3 pr-9 text-xs outline-none font-mono"
                                        style={{ borderColor: "var(--border)" }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowExaKey(!showExaKey)}
                                        className="absolute right-2 p-1 opacity-60 hover:opacity-100"
                                    >
                                        {showExaKey ? <EyeOff size={14} /> : <Eye size={14} />}
                                    </button>
                                </div>
                            </div>

                            <div className="flex h-9 items-center justify-between rounded-lg border px-3.5 mt-5 sm:mt-0" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <span className="text-xs font-medium">Enable Live Web Search</span>
                                <input
                                    type="checkbox"
                                    checked={settings.web_search_enabled}
                                    onChange={(e) => updateField("web_search_enabled", e.target.checked)}
                                    className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                />
                            </div>
                        </div>

                        <div className="mt-3 max-w-xs">
                            <label className="block text-xs font-medium mb-1 opacity-80">Max Search Results Per Query</label>
                            <input
                                type="number"
                                min={1}
                                max={20}
                                value={settings.web_search_max_results}
                                onChange={(e) => updateField("web_search_max_results", parseInt(e.target.value) || 5)}
                                className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                style={{ borderColor: "var(--border)" }}
                            />
                        </div>
                    </section>

                    {/* Section 3: Browser Automation */}
                    <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                        <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                            <Globe className="h-4 w-4 opacity-80" />
                            <h2 className="text-sm font-semibold">Browser Automation & Playwright Runtime</h2>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                            <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <span className="text-xs font-medium">Headless Mode</span>
                                <input
                                    type="checkbox"
                                    checked={settings.browser_headless}
                                    onChange={(e) => updateField("browser_headless", e.target.checked)}
                                    className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                />
                            </div>

                            <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <span className="text-xs font-medium">Enable Planning</span>
                                <input
                                    type="checkbox"
                                    checked={settings.browser_enable_planning}
                                    onChange={(e) => updateField("browser_enable_planning", e.target.checked)}
                                    className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                />
                            </div>

                            <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <span className="text-xs font-medium">Use Vision AI</span>
                                <input
                                    type="checkbox"
                                    checked={settings.browser_use_vision}
                                    onChange={(e) => updateField("browser_use_vision", e.target.checked)}
                                    className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Width (px)</label>
                                <input
                                    type="number"
                                    value={settings.browser_width}
                                    onChange={(e) => updateField("browser_width", parseInt(e.target.value) || 1280)}
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Height (px)</label>
                                <input
                                    type="number"
                                    value={settings.browser_height}
                                    onChange={(e) => updateField("browser_height", parseInt(e.target.value) || 720)}
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Max Steps</label>
                                <input
                                    type="number"
                                    value={settings.browser_max_steps}
                                    onChange={(e) => updateField("browser_max_steps", parseInt(e.target.value) || 10)}
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Max Failures</label>
                                <input
                                    type="number"
                                    value={settings.browser_max_failures}
                                    onChange={(e) => updateField("browser_max_failures", parseInt(e.target.value) || 2)}
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Wait Strategy</label>
                                <select
                                    value={settings.browser_wait_strategy}
                                    onChange={(e) => updateField("browser_wait_strategy", e.target.value)}
                                    className="h-9 w-full rounded-lg border bg-[var(--surface)] px-2.5 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                >
                                    <option value="smart">Smart Wait (DOM Mutation Detection)</option>
                                    <option value="fixed">Fixed Delay (Network Idle)</option>
                                    <option value="none">Immediate (No Wait)</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Page Timeout (sec)</label>
                                <input
                                    type="number"
                                    value={settings.browser_page_load_timeout}
                                    onChange={(e) => updateField("browser_page_load_timeout", parseInt(e.target.value) || 30)}
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                        </div>
                    </section>

                    {/* Section 4: Agent Behavior */}
                    <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                        <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                            <Bot className="h-4 w-4 opacity-80" />
                            <h2 className="text-sm font-semibold">Agent Behavior & Reflection Policies</h2>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                            <div className="space-y-3">
                                <div>
                                    <label className="block text-xs font-medium mb-1 opacity-80">Max Reflective Tool Iterations</label>
                                    <input
                                        type="number"
                                        value={settings.agent_max_tool_iterations}
                                        onChange={(e) => updateField("agent_max_tool_iterations", parseInt(e.target.value) || 5)}
                                        className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                        style={{ borderColor: "var(--border)" }}
                                    />
                                </div>

                                <div>
                                    <label className="block text-xs font-medium mb-1 opacity-80">Thinking Budget Level</label>
                                    <select
                                        value={settings.agent_thinking_budget}
                                        onChange={(e) => updateField("agent_thinking_budget", e.target.value)}
                                        className="h-9 w-full rounded-lg border bg-[var(--surface)] px-2.5 text-xs outline-none"
                                        style={{ borderColor: "var(--border)" }}
                                    >
                                        <option value="off">Off (Direct Response)</option>
                                        <option value="low">Low (Fast Reasoning)</option>
                                        <option value="medium">Medium (Balanced Context)</option>
                                        <option value="high">High (Deep Reflection)</option>
                                    </select>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                    <span className="text-xs font-medium">Reflect on Tool Use</span>
                                    <input
                                        type="checkbox"
                                        checked={settings.agent_reflect_on_tool_use}
                                        onChange={(e) => updateField("agent_reflect_on_tool_use", e.target.checked)}
                                        className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                    />
                                </div>

                                <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                    <span className="text-xs font-medium">Stream Thoughts in SSE</span>
                                    <input
                                        type="checkbox"
                                        checked={settings.agent_stream_thoughts}
                                        onChange={(e) => updateField("agent_stream_thoughts", e.target.checked)}
                                        className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                    />
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* Section 5: Session & Memory */}
                    <section className="rounded-xl border p-5 shadow-xs" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
                        <div className="flex items-center gap-2 border-b pb-3 mb-4" style={{ borderColor: "var(--border)" }}>
                            <Database className="h-4 w-4 opacity-80" />
                            <h2 className="text-sm font-semibold">Session Persistence & State Storage</h2>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
                            <div className="flex h-9 items-center justify-between rounded-lg border px-3.5" style={{ borderColor: "var(--border)", background: "var(--background)" }}>
                                <span className="text-xs font-medium">Persist Session History</span>
                                <input
                                    type="checkbox"
                                    checked={settings.session_persist}
                                    onChange={(e) => updateField("session_persist", e.target.checked)}
                                    className="h-4 w-4 accent-emerald-500 cursor-pointer"
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-medium mb-1 opacity-80">Max In-Memory Session Count</label>
                                <input
                                    type="number"
                                    value={settings.session_max_count}
                                    onChange={(e) => updateField("session_max_count", parseInt(e.target.value) || 50)}
                                    className="h-9 w-full rounded-lg border bg-transparent px-3 text-xs outline-none"
                                    style={{ borderColor: "var(--border)" }}
                                />
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        </AppLayout>
    );
}