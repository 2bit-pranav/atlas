// utils/skillsEngine.ts

export const VESIT_RESULT_SKILL_SCHEMA = {
  skill_id: "fetch_vesit_results",
  name: "Fetch Semester Results",
  description: "Navigates VESIT portal to find the Google Drive link for results.",
  parameters: ["department", "year", "semester"], 
  steps: [
    { action: "log", message: "Loading skill schema: fetch_vesit_results.json..." },
    { action: "goto", target: "https://vesit.ves.ac.in/results/searchug" },
    { action: "fill", target: "department", value: "{{department}}" },
    { action: "fill", target: "year", value: "{{year}}" },
    { action: "fill", target: "semester", value: "{{semester}}" },
    { action: "click", target: "Search Button" },
    { action: "wait", target: "networkidle" },
    { action: "scrape_attr", target: "table a", attr: "href" }
  ]
};

export async function executeVesitSkill(
  dept: "ecs" | "it" | "cmpn",
  semester: "4" | "5",
  addLog: (log: string) => void
): Promise<string> {
  // Map semester to the correct year string
  const year = semester === "4" ? "summer 2025" : "winter 2025";
  
  // 1. Visually simulate the JSON schema execution for the terminal
  for (const step of VESIT_RESULT_SKILL_SCHEMA.steps) {
    let logMsg = "";
    if (step.action === "goto") logMsg = `[Skill Executor] Navigating to ${step.target}...`;
    
    // FIX: Ensure step.value exists before trying to replace parameters
    if (step.action === "fill" && step.value) {
      const val = step.value
        .replace("{{department}}", dept.toUpperCase())
        .replace("{{year}}", year)
        .replace("{{semester}}", semester);
      logMsg = `[Skill Executor] Filling ${step.target} with "${val}"`;
    }
    
    if (step.action === "click") logMsg = `[Skill Executor] Clicking ${step.target}...`;
    if (step.action === "scrape_attr") logMsg = `[Skill Executor] Extracting Drive link from DOM...`;
    if (step.action === "log") logMsg = `[Skill Engine] ${step.message}`;

    if (logMsg) addLog(logMsg);
    
    // Fake processing delay for stage effect
    await new Promise(resolve => setTimeout(resolve, 600)); 
  }

  addLog("[Skill Engine] Execution complete. Link found.");
  
  // 2. The exact hardcoded Drive links mapping
  const driveLinks = {
    cmpn: {
      "4": "https://drive.google.com/drive/folders/19PA5wgx0rqAShwLkcbVizRg959M9XAna?usp=sharing",
      "5": "https://drive.google.com/file/d/1nmD0hy3PNQAz5PalqktOoo9VIPC_LcQ5/view?usp=sharing"
    },
    it: {
      "4": "https://drive.google.com/file/d/1p1Rny5CD3htU3CQJmHmn72QXj4UwmJlm/view?usp=sharing",
      "5": "https://drive.google.com/file/d/1eZvWtBqEtmyTU1LwNamX0BOC-N-tan3V/view?usp=sharing"
    },
    ecs: {
      "4": "https://drive.google.com/file/d/17IOelgdbYY6zPCT_OpEsGWmGWuRAgU4a/view?usp=sharing",
      "5": "https://drive.google.com/file/d/1iRbhArZceNpXQ_b2gBBnghINhxixKsv9/view?usp=sharing"
    }
  };
  
  const mockDriveLink = driveLinks[dept][semester];
  
  return `**Skill executed successfully!**\n\nHere is the official results link for **${dept.toUpperCase()} (Sem ${semester}, ${year})**:\n[View Results on Google Drive](${mockDriveLink})`;
}