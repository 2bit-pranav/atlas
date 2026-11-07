/**
 * How settings.json is laid out on the Settings page.
 *
 * The backend's `values` are flat dotted keys; this groups them into sections
 * and gives each a label, a control and a sentence of help. A key the schema
 * neither describes nor lists in HIDDEN still appears, under "Other", so a new
 * backend setting is never invisible; it just looks plainer until described.
 */

export type Control =
  | { type: "number"; min?: number; max?: number; step?: number }
  | { type: "slider"; min: number; max: number; step: number }
  | { type: "toggle" }
  | { type: "text" }
  | { type: "textarea"; rows?: number }
  | { type: "select"; options: string[] }
  | { type: "list" }
  /** The models in the models folder, from GET /models. */
  | { type: "model" }
  /** The Exa key: write-only, saved on its own (not a settings.json value). */
  | { type: "exaKey" }

export interface Field {
  key: string
  label: string
  help?: string
  control: Control
}

export interface Section {
  id: string
  title: string
  description: string
  /** Listed under Advanced in the nav: tuning most people never need. */
  advanced?: boolean
  groups: { title: string; fields: Field[] }[]
}

const num = (min?: number, max?: number, step?: number): Control => ({ type: "number", min, max, step })
const slider = (min: number, max: number, step: number): Control => ({ type: "slider", min, max, step })
const toggle: Control = { type: "toggle" }
const text: Control = { type: "text" }

export const SECTIONS: Section[] = [
  {
    id: "agent",
    title: "Agent",
    description: "What the agent is told and which built-in tools it has. These change results the most. Applies from the next message.",
    groups: [
      {
        title: "Instructions",
        fields: [
          { key: "system_prompt", label: "System prompt", control: { type: "textarea", rows: 8 },
            help: "Added to the harness's own prompt, never replacing it." },
        ],
      },
      {
        title: "Built-in tools",
        fields: [
          { key: "tools.builtin.write", label: "write", control: toggle, help: "Create or overwrite text files." },
          { key: "tools.builtin.edit", label: "edit", control: toggle, help: "Replace exact text in a file." },
          { key: "tools.builtin.shell", label: "shell", control: toggle,
            help: "Run commands. Every skill script runs through this, so skills need it." },
          { key: "tools.atlas.read_text", label: "read_text", control: toggle,
            help: "Read a text file by lines, or search it. Capped, so a long file cannot fill the context." },
          { key: "tools.atlas.read_image", label: "read_image", control: toggle, help: "Look at an image file." },
          { key: "tools.atlas.read_pdf", label: "read_pdf", control: toggle,
            help: "Read or search a PDF, scanned pages included. Parsed once, at upload." },
          { key: "tools.atlas.read_docx", label: "read_docx", control: toggle, help: "Read or search a Word document by section." },
          { key: "tools.atlas.read_xlsx", label: "read_xlsx", control: toggle,
            help: "Read a workbook's sheets and ranges, or total it with SQL." },
          { key: "tools.atlas.create_document", label: "create_document", control: toggle,
            help: "Write a Word, PDF or Excel file from Markdown. Comes with the pdf, docx and xlsx skills." },
          { key: "tools.atlas.edit_docx", label: "edit_docx", control: toggle,
            help: "Change one paragraph or table cell of a Word file. Comes with the docx skill." },
          { key: "tools.atlas.set_cell", label: "set_cell", control: toggle,
            help: "Change one cell of an Excel file. Comes with the xlsx skill." },
          { key: "tools.atlas.calculate", label: "calculate", control: toggle,
            help: "Exact arithmetic: totals, percentages, averages. Instead of the model adding in its head." },
          { key: "tools.atlas.dates", label: "dates", control: toggle,
            help: "Exact date counting: days between, weekdays, working days." },
          { key: "tools.atlas.find_files", label: "find_files", control: toggle,
            help: "Find your files by words in their name, folder or contents, across your folders." },
          { key: "tools.atlas.list_folder", label: "list_folder", control: toggle, help: "A folder's contents as a tree." },
          { key: "tools.atlas.copy_file", label: "copy_file", control: toggle, help: "Copy a file or folder. Never replaces a file." },
          { key: "tools.atlas.move_file", label: "move_file", control: toggle,
            help: "Move or rename. Never replaces a file; moving your files asks first." },
          { key: "tools.atlas.web_search", label: "web_search", control: toggle,
            help: "Search the web through Exa: a few relevant passages, each with its source. Needs the key below." },
          { key: "tools.atlas.read_url", label: "read_url", control: toggle,
            help: "Read a web page by its address. Fetched by Exa, never from this computer." },
          { key: "web.exa_key", label: "Exa key", control: { type: "exaKey" },
            help: "For web_search and read_url. Kept in Atlas's data folder; the agent can never read it. Get one at exa.ai." },
          { key: "tools.atlas.delete_file", label: "delete_file", control: toggle,
            help: "Delete by moving to the Recycle Bin. Deleting your files always asks first." },
          { key: "tools.ask", label: "Always ask before", control: { type: "list" },
            help: "Tool names (e.g. write, shell, create_document) that ask before every call, even where Access would let them run. MCP tools are set on the MCP page." },
        ],
      },
    ],
  },
  {
    id: "access",
    title: "Access",
    description: "What the agent may touch beyond its chat workspace, and what it must ask about. Applies from the next message.",
    groups: [
      {
        title: "Allowed folders",
        fields: [
          { key: "access.folders", label: "Folders", control: { type: "list" },
            help: "One per line, e.g. C:/Users/you/Documents. Subfolders are included. The chat workspace is always allowed. Used by the file tools, the document tools, shell commands and any MCP server whose arguments contain {atlas:folders}." },
          { key: "access.ask_outside", label: "Ask before going outside them", control: toggle,
            help: "On: anything outside shows an Allow / Deny card. Off: it is refused." },
          { key: "access.mode", label: "Mode", control: { type: "select", options: ["look", "ask", "work"] },
            help: "Look: reads only. Ask: asks before changing, deleting or running anything in your folders. Work: changes your folders without asking; deleting still asks, and nothing outside them runs without asking." },
        ],
      },
      {
        title: "Approvals",
        fields: [
          { key: "approvals.timeout", label: "Seconds to wait for an answer", control: num(30, 120, 5),
            help: "No answer counts as Deny. Installs always ask; MCP tools ask unless set to On on the MCP page." },
        ],
      },
    ],
  },
  {
    id: "model",
    title: "Model",
    description: "Which local model answers. A new model or context size takes effect after Restart.",
    groups: [
      {
        title: "Model",
        fields: [
          { key: "model.name", label: "Model", control: { type: "model" },
            help: "A folder in the models folder (llm/ unless changed under Server & storage). Restart to load it." },
          { key: "sampling.thinking", label: "Think by default", control: toggle,
            help: "The starting state of the thinking switch in the composer." },
          { key: "model.context_size", label: "Context size", control: num(512, 262144, 512),
            help: "Tokens the model can hold at once. Larger needs more GPU memory." },
        ],
      },
    ],
  },
  {
    id: "behaviour",
    title: "Recovery & context",
    advanced: true,
    description: "How the agent recovers from failures, what a retry changes, and how long chats are trimmed. Applies from the next message.",
    groups: [
      {
        title: "Recovery",
        fields: [
          { key: "resilience.model_attempts", label: "Model call attempts", control: num(1, 10, 1),
            help: "When llama-server errors or returns nothing." },
          { key: "resilience.model_retry_delay", label: "Seconds between attempts", control: num(0, 30, 0.5) },
          { key: "resilience.tool_crash_retries", label: "Re-runs of a crashed tool", control: num(0, 5, 1) },
          { key: "resilience.tool_failure_limit", label: "Failed tool calls per turn", control: num(1, 10, 1),
            help: "After this many, the model is told to stop and explain." },
          { key: "resilience.nudge_after_failure", label: "Push back when the model gives up", control: toggle,
            help: "If the model stops right after a failed tool call, re-invoke it once." },
        ],
      },
      {
        title: "Limits",
        fields: [
          { key: "limits.max_model_calls", label: "Model calls per message", control: num(1, 500, 1),
            help: "The run stops with a message past this; reply \"continue\" to go on." },
          { key: "limits.max_minutes", label: "Minutes per message", control: num(1, 240, 1) },
          { key: "limits.repeat_limit", label: "Same tool call allowed", control: num(1, 20, 1),
            help: "The same tool with the same arguments, in one message. The next one is refused." },
        ],
      },
      {
        title: "Retries",
        fields: [
          { key: "retry.show_previous", label: "Show earlier answers", control: toggle,
            help: "Tell the model what the earlier versions said and ask for a different approach. The strongest lever for a genuinely different answer." },
          { key: "retry.previous_limit", label: "Earlier answers quoted", control: num(1, 5, 1) },
          { key: "retry.previous_chars", label: "Characters per quote", control: num(100, 4000, 50) },
          { key: "retry.instructions", label: "Retry instruction", control: { type: "textarea", rows: 3 } },
          { key: "retry.temperature_boost", label: "Temperature boost", control: slider(0, 1, 0.05),
            help: "Added to the temperature for a retry only." },
          { key: "retry.presence_penalty", label: "Presence penalty on retry", control: slider(-2, 2, 0.05) },
          { key: "retry.new_seed", label: "New seed per retry", control: toggle },
        ],
      },
      {
        title: "Context",
        fields: [
          { key: "context.conversation_manager", label: "Conversation manager",
            control: { type: "select", options: ["null", "sliding", "summarizing"] },
            help: "How history is trimmed when it nears the window. 'null' keeps everything." },
          { key: "context.window", label: "Context window", control: num(512, 262144, 512) },
          { key: "context.prune_trigger_ratio", label: "Trim at", control: slider(0.1, 0.95, 0.05) },
          { key: "context.prune_target_ratio", label: "Trim down to", control: slider(0.05, 0.9, 0.05) },
          { key: "context.generation_reserve", label: "Reserved for the answer", control: num(256, 32768, 256) },
        ],
      },
    ],
  },
  {
    id: "generation",
    title: "Generation",
    advanced: true,
    description: "Sampling sent to the model with every request. The same for any model. Applies from the next message.",
    groups: [
      {
        title: "Sampling",
        fields: [
          { key: "sampling.temperature", label: "Temperature", control: slider(0, 2, 0.05),
            help: "Higher is more varied, lower is more predictable." },
          { key: "sampling.top_p", label: "Top P", control: slider(0, 1, 0.01),
            help: "Keep the smallest set of tokens whose probability adds up to this." },
          { key: "sampling.top_k", label: "Top K", control: num(0, 200, 1),
            help: "Only consider the K most likely tokens. 0 disables." },
          { key: "sampling.min_p", label: "Min P", control: slider(0, 1, 0.01),
            help: "Drop tokens less likely than this fraction of the top token." },
          { key: "sampling.max_tokens", label: "Max tokens", control: num(1, 32768, 1),
            help: "Longest answer per model call." },
        ],
      },
      {
        title: "Penalties",
        fields: [
          { key: "sampling.repeat_penalty", label: "Repeat penalty", control: slider(0.5, 2, 0.01) },
          { key: "sampling.presence_penalty", label: "Presence penalty", control: slider(-2, 2, 0.05) },
          { key: "sampling.frequency_penalty", label: "Frequency penalty", control: slider(-2, 2, 0.05) },
        ],
      },
    ],
  },
  {
    id: "server",
    title: "Server & storage",
    advanced: true,
    description: "How llama-server is launched and where Atlas keeps its files. Takes effect after Restart.",
    groups: [
      {
        title: "llama-server",
        fields: [
          { key: "model.dir", label: "Models folder", control: text,
            help: "One subfolder per model with its .gguf (and an mmproj file for image input). Relative to the application folder." },
          { key: "model.supports_thinking", label: "Allow thinking", control: toggle,
            help: "Atlas reads whether the model can think from its files. Turn off to hide the switch anyway; turning on cannot add what the model lacks." },
          { key: "model.supports_vision", label: "Allow images", control: toggle,
            help: "The same for images: read from the model's projector file. Off stops images reaching the model." },
          { key: "model.gpu_layers", label: "GPU layers", control: text, help: "A number, or 'all'." },
          { key: "model.threads", label: "CPU threads", control: num(1, 128, 1) },
          { key: "model.batch_size", label: "Batch size", control: num(1, 16384, 1) },
          { key: "model.ubatch_size", label: "Micro-batch size", control: num(1, 16384, 1) },
          { key: "model.flash_attention", label: "Flash attention", control: toggle },
          { key: "model.jinja", label: "Jinja templates", control: toggle },
          { key: "model.reasoning", label: "Reasoning format", control: { type: "select", options: ["auto", "on", "off"] } },
          { key: "model.parallel_slots", label: "Parallel slots", control: num(1, 8, 1) },
          { key: "llamacpp.binary", label: "Binary", control: text },
          { key: "llamacpp.subcommand", label: "Subcommand", control: text },
          { key: "llamacpp.extra_args", label: "Extra arguments", control: { type: "list" }, help: "One per line." },
        ],
      },
      {
        title: "Ports",
        fields: [
          { key: "ports.llama", label: "llama-server", control: num(1, 65535, 1) },
          { key: "ports.backend", label: "Backend", control: num(1, 65535, 1) },
          { key: "ports.client", label: "Web UI", control: num(1, 65535, 1),
            help: "Restart does not move the web UI: stop and start Atlas for this one." },
        ],
      },
      {
        title: "Storage",
        fields: [
          { key: "paths.data_dir", label: "Data folder", control: text },
          { key: "session.dir", label: "Snapshots folder", control: text, help: "Inside the data folder." },
          { key: "skills.dir", label: "Skills folder", control: text },
          { key: "mcp.config", label: "MCP config file", control: text },
          { key: "mcp.startup_timeout", label: "MCP startup timeout (s)", control: num(1, 600, 1) },
        ],
      },
    ],
  },
]

/** Keys shown elsewhere (Skills, MCP pages) or deliberately not editable. */
export const HIDDEN = new Set(["skills.disabled", "memory.enabled", "tools.interventions"])

export function describedKeys(): Set<string> {
  return new Set(SECTIONS.flatMap((s) => s.groups.flatMap((g) => g.fields.map((f) => f.key))))
}
