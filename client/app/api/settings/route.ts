import { NextResponse } from "next/server";

const FASTAPI_URL = "http://127.0.0.1:8001/settings";

const defaultSettings = {
    model: {
        local: {
            name: "gemma-4-E2B_q4_0-it.gguf",
            base_url: "http://127.0.0.1:8000/v1",
            temperature: 0.2,
            top_p: 0.9,
            top_k: 40,
            context_window: 8192,
        },
        cloud: {
            provider: "google",
            name: "gemini-3.5-flash-lite",
            api_key: "",
            base_url: "https://generativelanguage.googleapis.com/v1beta/openai/",
        },
    },
    agent_runtime: {
        default_mode: "local",
        max_tool_iterations: 5,
        reflect_on_tool_use: true,
        system_prompt_extra: "",
    },
    tools: {
        exa: {
            api_key: "",
            max_results: 5,
        },
    },
    system: {
        download_directory: "",
    },
};

export async function GET(req: Request) {
    try {
        const { searchParams } = new URL(req.url);
        const reveal = searchParams.get("reveal");
        const targetUrl = reveal !== null ? `${FASTAPI_URL}?reveal=${reveal}` : FASTAPI_URL;

        const res = await fetch(targetUrl, { cache: "no-store" });
        if (res.ok) {
            const data = await res.json();
            return NextResponse.json(data);
        }
    } catch {
        // FastAPI server not reachable or starting up; return default settings structure cleanly
    }
    return NextResponse.json(defaultSettings);
}

export async function POST(req: Request) {
    try {
        const { searchParams } = new URL(req.url);
        const reveal = searchParams.get("reveal");
        const targetUrl = reveal !== null ? `${FASTAPI_URL}?reveal=${reveal}` : FASTAPI_URL;
        const body = await req.json();

        const res = await fetch(targetUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            const data = await res.json();
            return NextResponse.json(data);
        }
    } catch {
        // Connection error
    }
    return NextResponse.json({ error: "Could not connect to backend server on port 8001" }, { status: 503 });
}