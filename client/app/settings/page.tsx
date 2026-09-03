"use client";

import { useEffect, useState } from "react";
import { Eye, EyeOff, AlertCircle, Check } from "lucide-react";
import { useRouter } from "next/navigation";

interface Settings {
    // Inference Engine
    local_model_url: string;
    local_model_name: string;
    cloud_provider: string;
    cloud_model_name: string;
    cloud_api_key: string;
    // Web Research
    exa_api_key: string;
    web_search_enabled: boolean;
    web_search_max_results: number;
    // Browser Automation
    browser_headless: boolean;
    browser_width: number;
    browser_height: number;
    browser_max_steps: number;
    browser_max_failures: number;
    browser_enable_planning: boolean;
    browser_wait_strategy: string;
    browser_page_load_timeout: number;
    browser_use_vision: boolean;
    // Agent Behavior
    agent_max_tool_iterations: number;
    agent_reflect_on_tool_use: boolean;
    agent_stream_thoughts: boolean;
    agent_thinking_budget: string;
    // Session & Memory
    session_persist: boolean;
    session_max_count: number;
}

export default function SettingsPage() {
    const router = useRouter();
    const [settings, setSettings] = useState<Settings | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [showCloudApiKey, setShowCloudApiKey] = useState(false);
    const [showExaApiKey, setShowExaApiKey] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);

    useEffect(() => {
        fetchSettings();
    }, []);

    const fetchSettings = async () => {
        try {
            const res = await fetch("http://localhost:8001/api/settings");
            if (res.ok) {
                const data = await res.json();
                setSettings(data);
            }
        } catch (error) {
            console.error("Failed to fetch settings:", error);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        if (!settings) return;
        setSaving(true);
        try {
            const res = await fetch("http://localhost:8001/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(settings),
            });
            if (res.ok) {
                setSaveSuccess(true);
                setTimeout(() => setSaveSuccess(false), 2000);
            }
        } catch (error) {
            console.error("Failed to save settings:", error);
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div
                className="flex items-center justify-center h-screen"
                style={{ background: "var(--background)" }}
            >
                <div className="text-center">
                    <div
                        className="w-8 h-8 border-4 border-transparent rounded-full animate-spin mb-4 mx-auto"
                        style={{
                            borderTopColor: "var(--text)",
                            borderRightColor: "var(--text)",
                        }}
                    />
                    <p style={{ color: "var(--muted)" }}>Loading settings...</p>
                </div>
            </div>
        );
    }

    if (!settings) {
        return (
            <div
                className="flex items-center justify-center h-screen"
                style={{ background: "var(--background)" }}
            >
                <p style={{ color: "var(--muted)" }}>Failed to load settings</p>
            </div>
        );
    }

    const handleChange = (key: keyof Settings, value: any) => {
        setSettings((prev) => prev ? { ...prev, [key]: value } : null);
    };

    return (
        <div
            className="h-screen overflow-auto"
            style={{ background: "var(--background)" }}
        >
            <div className="max-w-3xl mx-auto p-6 sm:p-8">
                <div className="mb-8">
                    <h1
                        className="text-3xl font-bold mb-2"
                        style={{ color: "var(--text)" }}
                    >
                        Settings
                    </h1>
                    <p style={{ color: "var(--muted)" }} className="text-sm">
                        Configure Atlas parameters and behavior
                    </p>
                </div>

                {/* Inference Engine Section */}
                <Section title="Inference Engine" description="Configure model endpoints and API keys">
                    <div className="space-y-6">
                        {/* Local Model */}
                        <div className="border-b pb-6" style={{ borderColor: "var(--border)" }}>
                            <h3
                                className="text-sm font-semibold mb-4"
                                style={{ color: "var(--text)" }}
                            >
                                Local Model
                            </h3>
                            <div className="space-y-4">
                                <div>
                                    <label
                                        className="block text-sm font-medium mb-2"
                                        style={{ color: "var(--text)" }}
                                    >
                                        Base URL
                                    </label>
                                    <input
                                        type="text"
                                        value={settings.local_model_url}
                                        onChange={(e) =>
                                            handleChange("local_model_url", e.target.value)
                                        }
                                        placeholder="http://127.0.0.1:8000/v1"
                                        className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                        style={{
                                            background: "var(--surface)",
                                            border: "1px solid var(--border)",
                                            color: "var(--text)",
                                        }}
                                        onFocus={(e) => {
                                            const hint = document.getElementById(
                                                "local-url-hint"
                                            );
                                            if (hint) hint.style.display = "block";
                                        }}
                                        onBlur={(e) => {
                                            const hint = document.getElementById(
                                                "local-url-hint"
                                            );
                                            if (hint) hint.style.display = "none";
                                        }}
                                    />
                                    <p
                                        id="local-url-hint"
                                        className="text-xs mt-2 hidden"
                                        style={{ color: "var(--muted)" }}
                                    >
                                        Must be OpenAI-compatible API endpoint
                                    </p>
                                </div>
                                <div>
                                    <label
                                        className="block text-sm font-medium mb-2"
                                        style={{ color: "var(--text)" }}
                                    >
                                        Model Name
                                    </label>
                                    <input
                                        type="text"
                                        value={settings.local_model_name}
                                        onChange={(e) =>
                                            handleChange("local_model_name", e.target.value)
                                        }
                                        placeholder="gemma-4-E2B_q4_0-it.gguf"
                                        className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                        style={{
                                            background: "var(--surface)",
                                            border: "1px solid var(--border)",
                                            color: "var(--text)",
                                        }}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Cloud Model */}
                        <div>
                            <h3
                                className="text-sm font-semibold mb-4"
                                style={{ color: "var(--text)" }}
                            >
                                Cloud Model
                            </h3>
                            <div className="space-y-4">
                                <div>
                                    <label
                                        className="block text-sm font-medium mb-2"
                                        style={{ color: "var(--text)" }}
                                    >
                                        Provider
                                    </label>
                                    <select
                                        value={settings.cloud_provider}
                                        onChange={(e) =>
                                            handleChange("cloud_provider", e.target.value)
                                        }
                                        className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                        style={{
                                            background: "var(--surface)",
                                            border: "1px solid var(--border)",
                                            color: "var(--text)",
                                        }}
                                    >
                                        <option value="google">Google Gemini</option>
                                        <option value="openai">OpenAI ChatGPT</option>
                                        <option value="anthropic">Anthropic Claude</option>
                                    </select>
                                </div>
                                <div>
                                    <label
                                        className="block text-sm font-medium mb-2"
                                        style={{ color: "var(--text)" }}
                                    >
                                        Model Name
                                    </label>
                                    <input
                                        type="text"
                                        value={settings.cloud_model_name}
                                        onChange={(e) =>
                                            handleChange("cloud_model_name", e.target.value)
                                        }
                                        placeholder="gemini-3.5-flash-lite"
                                        className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                        style={{
                                            background: "var(--surface)",
                                            border: "1px solid var(--border)",
                                            color: "var(--text)",
                                        }}
                                    />
                                </div>
                                <div>
                                    <label
                                        className="block text-sm font-medium mb-2"
                                        style={{ color: "var(--text)" }}
                                    >
                                        API Key
                                    </label>
                                    <div className="relative">
                                        <input
                                            type={showCloudApiKey ? "text" : "password"}
                                            value={settings.cloud_api_key}
                                            onChange={(e) =>
                                                handleChange("cloud_api_key", e.target.value)
                                            }
                                            placeholder="••••••••••••••••"
                                            className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all pr-10"
                                            style={{
                                                background: "var(--surface)",
                                                border: "1px solid var(--border)",
                                                color: "var(--text)",
                                            }}
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowCloudApiKey(!showCloudApiKey)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2"
                                            style={{ color: "var(--muted)" }}
                                        >
                                            {showCloudApiKey ? (
                                                <EyeOff size={16} />
                                            ) : (
                                                <Eye size={16} />
                                            )}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </Section>

                {/* Web Research Section */}
                <Section title="Web Research" description="Configure search and data retrieval">
                    <div className="space-y-4">
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Exa API Key
                            </label>
                            <div className="relative">
                                <input
                                    type={showExaApiKey ? "text" : "password"}
                                    value={settings.exa_api_key}
                                    onChange={(e) =>
                                        handleChange("exa_api_key", e.target.value)
                                    }
                                    placeholder="••••••••••••••••"
                                    className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all pr-10"
                                    style={{
                                        background: "var(--surface)",
                                        border: "1px solid var(--border)",
                                        color: "var(--text)",
                                    }}
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowExaApiKey(!showExaApiKey)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2"
                                    style={{ color: "var(--muted)" }}
                                >
                                    {showExaApiKey ? (
                                        <EyeOff size={16} />
                                    ) : (
                                        <Eye size={16} />
                                    )}
                                </button>
                            </div>
                        </div>
                        <div className="flex items-center justify-between">
                            <label
                                className="text-sm font-medium"
                                style={{ color: "var(--text)" }}
                            >
                                Enable Web Search
                            </label>
                            <Toggle
                                checked={settings.web_search_enabled}
                                onChange={(checked) =>
                                    handleChange("web_search_enabled", checked)
                                }
                            />
                        </div>
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Max Results
                            </label>
                            <input
                                type="number"
                                value={settings.web_search_max_results}
                                onChange={(e) =>
                                    handleChange(
                                        "web_search_max_results",
                                        parseInt(e.target.value)
                                    )
                                }
                                min="1"
                                max="50"
                                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                style={{
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                }}
                            />
                        </div>
                    </div>
                </Section>

                {/* Browser Automation Section */}
                <Section title="Browser Automation" description="Configure web browser interaction parameters">
                    <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label
                                    className="block text-sm font-medium mb-2"
                                    style={{ color: "var(--text)" }}
                                >
                                    Window Width (px)
                                </label>
                                <input
                                    type="number"
                                    value={settings.browser_width}
                                    onChange={(e) =>
                                        handleChange("browser_width", parseInt(e.target.value))
                                    }
                                    min="800"
                                    max="4096"
                                    className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                    style={{
                                        background: "var(--surface)",
                                        border: "1px solid var(--border)",
                                        color: "var(--text)",
                                    }}
                                />
                            </div>
                            <div>
                                <label
                                    className="block text-sm font-medium mb-2"
                                    style={{ color: "var(--text)" }}
                                >
                                    Window Height (px)
                                </label>
                                <input
                                    type="number"
                                    value={settings.browser_height}
                                    onChange={(e) =>
                                        handleChange(
                                            "browser_height",
                                            parseInt(e.target.value)
                                        )
                                    }
                                    min="600"
                                    max="4096"
                                    className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                    style={{
                                        background: "var(--surface)",
                                        border: "1px solid var(--border)",
                                        color: "var(--text)",
                                    }}
                                />
                            </div>
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label
                                    className="block text-sm font-medium mb-2"
                                    style={{ color: "var(--text)" }}
                                >
                                    Max Steps
                                </label>
                                <input
                                    type="number"
                                    value={settings.browser_max_steps}
                                    onChange={(e) =>
                                        handleChange(
                                            "browser_max_steps",
                                            parseInt(e.target.value)
                                        )
                                    }
                                    min="1"
                                    max="100"
                                    className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                    style={{
                                        background: "var(--surface)",
                                        border: "1px solid var(--border)",
                                        color: "var(--text)",
                                    }}
                                />
                            </div>
                            <div>
                                <label
                                    className="block text-sm font-medium mb-2"
                                    style={{ color: "var(--text)" }}
                                >
                                    Max Failures
                                </label>
                                <input
                                    type="number"
                                    value={settings.browser_max_failures}
                                    onChange={(e) =>
                                        handleChange(
                                            "browser_max_failures",
                                            parseInt(e.target.value)
                                        )
                                    }
                                    min="0"
                                    max="10"
                                    className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                    style={{
                                        background: "var(--surface)",
                                        border: "1px solid var(--border)",
                                        color: "var(--text)",
                                    }}
                                />
                            </div>
                        </div>
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Page Load Timeout (seconds)
                            </label>
                            <input
                                type="number"
                                value={settings.browser_page_load_timeout}
                                onChange={(e) =>
                                    handleChange(
                                        "browser_page_load_timeout",
                                        parseInt(e.target.value)
                                    )
                                }
                                min="5"
                                max="300"
                                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                style={{
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                }}
                            />
                        </div>
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Wait Strategy
                            </label>
                            <select
                                value={settings.browser_wait_strategy}
                                onChange={(e) =>
                                    handleChange("browser_wait_strategy", e.target.value)
                                }
                                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                style={{
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                }}
                            >
                                <option value="smart">Smart</option>
                                <option value="network_idle">Network Idle</option>
                                <option value="load">Load Complete</option>
                            </select>
                        </div>
                        <div className="space-y-3">
                            <div className="flex items-center justify-between">
                                <label
                                    className="text-sm font-medium"
                                    style={{ color: "var(--text)" }}
                                >
                                    Headless Mode
                                </label>
                                <Toggle
                                    checked={settings.browser_headless}
                                    onChange={(checked) =>
                                        handleChange("browser_headless", checked)
                                    }
                                />
                            </div>
                            <div className="flex items-center justify-between">
                                <label
                                    className="text-sm font-medium"
                                    style={{ color: "var(--text)" }}
                                >
                                    Enable Planning
                                </label>
                                <Toggle
                                    checked={settings.browser_enable_planning}
                                    onChange={(checked) =>
                                        handleChange("browser_enable_planning", checked)
                                    }
                                />
                            </div>
                            <div className="flex items-center justify-between">
                                <label
                                    className="text-sm font-medium"
                                    style={{ color: "var(--text)" }}
                                >
                                    Use Vision
                                </label>
                                <Toggle
                                    checked={settings.browser_use_vision}
                                    onChange={(checked) =>
                                        handleChange("browser_use_vision", checked)
                                    }
                                />
                            </div>
                        </div>
                    </div>
                </Section>

                {/* Agent Behavior Section */}
                <Section title="Agent Behavior" description="Configure reasoning and execution parameters">
                    <div className="space-y-4">
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Max Tool Iterations
                            </label>
                            <input
                                type="number"
                                value={settings.agent_max_tool_iterations}
                                onChange={(e) =>
                                    handleChange(
                                        "agent_max_tool_iterations",
                                        parseInt(e.target.value)
                                    )
                                }
                                min="1"
                                max="20"
                                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                style={{
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                }}
                            />
                        </div>
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Default Thinking Budget
                            </label>
                            <select
                                value={settings.agent_thinking_budget}
                                onChange={(e) =>
                                    handleChange("agent_thinking_budget", e.target.value)
                                }
                                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                style={{
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                }}
                            >
                                <option value="off">Off</option>
                                <option value="low">Low (512 tokens)</option>
                                <option value="medium">Medium (2048 tokens)</option>
                                <option value="high">High (8192 tokens)</option>
                            </select>
                        </div>
                        <div className="space-y-3">
                            <div className="flex items-center justify-between">
                                <label
                                    className="text-sm font-medium"
                                    style={{ color: "var(--text)" }}
                                >
                                    Reflect on Tool Use
                                </label>
                                <Toggle
                                    checked={settings.agent_reflect_on_tool_use}
                                    onChange={(checked) =>
                                        handleChange("agent_reflect_on_tool_use", checked)
                                    }
                                />
                            </div>
                            <div className="flex items-center justify-between">
                                <label
                                    className="text-sm font-medium"
                                    style={{ color: "var(--text)" }}
                                >
                                    Stream Thoughts
                                </label>
                                <Toggle
                                    checked={settings.agent_stream_thoughts}
                                    onChange={(checked) =>
                                        handleChange("agent_stream_thoughts", checked)
                                    }
                                />
                            </div>
                        </div>
                    </div>
                </Section>

                {/* Session & Memory Section */}
                <Section title="Session & Memory" description="Configure persistence and storage">
                    <div className="space-y-4">
                        <div>
                            <label
                                className="block text-sm font-medium mb-2"
                                style={{ color: "var(--text)" }}
                            >
                                Max Sessions
                            </label>
                            <input
                                type="number"
                                value={settings.session_max_count}
                                onChange={(e) =>
                                    handleChange(
                                        "session_max_count",
                                        parseInt(e.target.value)
                                    )
                                }
                                min="1"
                                max="500"
                                className="w-full px-3 py-2 rounded-lg text-sm outline-none transition-all"
                                style={{
                                    background: "var(--surface)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text)",
                                }}
                            />
                        </div>
                        <div className="flex items-center justify-between">
                            <label
                                className="text-sm font-medium"
                                style={{ color: "var(--text)" }}
                            >
                                Persist Sessions
                            </label>
                            <Toggle
                                checked={settings.session_persist}
                                onChange={(checked) =>
                                    handleChange("session_persist", checked)
                                }
                            />
                        </div>
                    </div>
                </Section>

                {/* Action Buttons */}
                <div className="mt-8 flex gap-3">
                    <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex items-center gap-2 px-6 py-2 rounded-lg text-sm font-medium transition-all"
                        style={{
                            background: "var(--text)",
                            color: "var(--background)",
                            opacity: saving ? 0.7 : 1,
                            cursor: saving ? "not-allowed" : "pointer",
                        }}
                    >
                        {saveSuccess ? (
                            <>
                                <Check size={16} />
                                Saved
                            </>
                        ) : (
                            "Save Changes"
                        )}
                    </button>
                    <button
                        onClick={() => router.push("/")}
                        className="px-6 py-2 rounded-lg text-sm font-medium transition-all"
                        style={{
                            background: "var(--surface)",
                            border: "1px solid var(--border)",
                            color: "var(--text)",
                        }}
                    >
                        Back to Chat
                    </button>
                </div>
            </div>
        </div>
    );
}

interface SectionProps {
    title: string;
    description: string;
    children: React.ReactNode;
}

function Section({ title, description, children }: SectionProps) {
    return (
        <div
            className="mb-8 p-6 rounded-xl"
            style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
            }}
        >
            <div className="mb-6">
                <h2
                    className="text-lg font-semibold mb-1"
                    style={{ color: "var(--text)" }}
                >
                    {title}
                </h2>
                <p style={{ color: "var(--muted)" }} className="text-sm">
                    {description}
                </p>
            </div>
            {children}
        </div>
    );
}

interface ToggleProps {
    checked: boolean;
    onChange: (checked: boolean) => void;
}

function Toggle({ checked, onChange }: ToggleProps) {
    return (
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none"
            style={{
                background: checked ? "var(--text)" : "var(--surface-hover)",
                border: "1px solid var(--border)",
            }}
        >
            <span
                className="pointer-events-none inline-block h-5 w-5 transform rounded-full shadow transition duration-200 ease-in-out"
                style={{
                    background: checked ? "var(--background)" : "var(--muted)",
                    transform: checked ? "translateX(20px)" : "translateX(2px)",
                    marginTop: "1px",
                }}
            />
        </button>
    );
}
