import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

// settings.json at project root (two levels up from client/app/api/settings)
const rootPath = path.resolve(process.cwd(), "..", "settings.json");

const defaultSettings = {
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

export async function GET() {
    try {
        if (fs.existsSync(rootPath)) {
            const content = fs.readFileSync(rootPath, "utf-8");
            return NextResponse.json({ ...defaultSettings, ...JSON.parse(content) });
        }
    } catch (e) {
        console.error("Error reading settings.json:", e);
    }
    return NextResponse.json(defaultSettings);
}

export async function POST(req: Request) {
    try {
        const body = await req.json();
        const updated = { ...defaultSettings, ...body };
        fs.writeFileSync(rootPath, JSON.stringify(updated, null, 2), "utf-8");
        return NextResponse.json(updated);
    } catch (e) {
        console.error("Error writing settings.json:", e);
        return NextResponse.json({ error: "Failed to write settings file" }, { status: 500 });
    }
}