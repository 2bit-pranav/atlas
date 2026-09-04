import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

// memory.json at project root
const rootPath = path.resolve(process.cwd(), "..", "memory.json");

const defaultFacts = [
    {
        id: "fact-1",
        text: "User prefers train travel over flights for domestic trips",
        category: "Preferences",
        created_at: "2026-09-01",
    },
    {
        id: "fact-2",
        text: "Target budget range for hardware/laptop recommendations is under ",
        category: "Budget",
        created_at: "2026-09-02",
    },
    {
        id: "fact-3",
        text: "Default UI color theme preference is Dark Mode",
        category: "UI Settings",
        created_at: "2026-09-03",
    },
];

export async function GET() {
    try {
        if (fs.existsSync(rootPath)) {
            const content = fs.readFileSync(rootPath, "utf-8");
            return NextResponse.json({ facts: JSON.parse(content) });
        }
    } catch (e) {
        console.error("Error reading memory.json:", e);
    }
    // Write default if not existing
    try {
        fs.writeFileSync(rootPath, JSON.stringify(defaultFacts, null, 2), "utf-8");
    } catch {}
    return NextResponse.json({ facts: defaultFacts });
}

export async function POST(req: Request) {
    try {
        const body = await req.json();
        const facts = Array.isArray(body.facts) ? body.facts : [];
        fs.writeFileSync(rootPath, JSON.stringify(facts, null, 2), "utf-8");
        return NextResponse.json({ facts });
    } catch (e) {
        console.error("Error writing memory.json:", e);
        return NextResponse.json({ error: "Failed to write memory file" }, { status: 500 });
    }
}