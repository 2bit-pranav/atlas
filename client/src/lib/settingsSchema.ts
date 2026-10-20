/**
 * How settings.json is laid out on the Settings page.
 *
 * The backend's `values` are flat dotted keys; this groups them into sections
 * and gives each a label, a control and a sentence of help. A key the schema
 * does not mention still appears, under "Other", so a new backend setting is
 * never invisible -- it just looks plainer until it is described here.
 */

export type Control =
  | { type: "number"; min?: number; max?: number; step?: number }
  | { type: "slider"; min: number; max: number; step: number }
  | { type: "toggle" }
  | { type: "text" }
  | { type: "textarea"; rows?: number }
  | { type: "select"; options: string[] }
  | { type: "list" }

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
  groups: { title: string; fields: Field[] }[]
}

const num = (min?: number, max?: number, step?: number): Control => ({ type: "number", min, max, step })
const slider = (min: number, max: number, step: number): Control => ({ type: "slider", min, max, step })
const toggle: Control = { type: "toggle" }
const text: Control = { type: "text" }

export const SECTIONS: Section[] = [
  {
    id: "llm",
    title: "LLM",
    description: "Sampling sent to the model with every request. Applies from the next message.",
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
      {
        title: "Reasoning",
        fields: [
          { key: "sampling.thinking", label: "Think by default", control: toggle,
            help: "The starting state of the thinking switch in the composer." },
        ],
      },
    ],
  },
  {
    id: "agent",
    title: "Agent",
    description: "What the Strands agent is told and allowed to do. Applies from the next message.",
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
          { key: "tools.builtin.read", label: "read", control: toggle, help: "Read text files and images." },
          { key: "tools.builtin.write", label: "write", control: toggle, help: "Create or overwrite text files." },
          { key: "tools.builtin.edit", label: "edit", control: toggle, help: "Replace exact text in a file." },
          { key: "tools.builtin.shell", label: "shell", control: toggle,
            help: "Run commands. Every skill script runs through this, so skills need it." },
          { key: "tools.builtin.web_fetch", label: "web_fetch", control: toggle,
            help: "Fetch a web page as text. Leaves this machine." },
          { key: "tools.builtin.subagent", label: "subagent", control: toggle,
            help: "Delegate a task to a child agent. Slow with one llama slot." },
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
        ],
      },
      {
        title: "Approvals",
        fields: [
          { key: "approvals.timeout", label: "Seconds to wait for an answer", control: num(30, 120, 5),
            help: "No answer counts as Deny. Installs always ask; MCP tools ask when set to Ask on the MCP page." },
        ],
      },
    ],
  },
  {
    id: "server",
    title: "Model & server",
    description: "How llama-server is launched. Saved now, used at the next `atlas stop` + `atlas start`.",
    groups: [
      {
        title: "Model",
        fields: [
          { key: "model.dir", label: "Models folder", control: text,
            help: "One subfolder per model, holding its .gguf (and an mmproj file for image input). Relative to the application folder." },
          { key: "model.name", label: "Default model", control: text,
            help: "The subfolder name of the model to load at start and use for chats, e.g. gemma." },
          { key: "model.context_size", label: "Context size", control: num(512, 262144, 512),
            help: "These values apply to every model in the folder." },
          { key: "model.gpu_layers", label: "GPU layers", control: text, help: "A number, or 'all'." },
          { key: "model.threads", label: "CPU threads", control: num(1, 128, 1) },
          { key: "model.batch_size", label: "Batch size", control: num(1, 16384, 1) },
          { key: "model.ubatch_size", label: "Micro-batch size", control: num(1, 16384, 1) },
          { key: "model.flash_attention", label: "Flash attention", control: toggle },
          { key: "model.jinja", label: "Jinja templates", control: toggle },
          { key: "model.reasoning", label: "Reasoning format", control: { type: "select", options: ["auto", "on", "off"] } },
          { key: "model.parallel_slots", label: "Parallel slots", control: num(1, 8, 1) },
          { key: "model.supports_thinking", label: "Model can think", control: toggle },
          { key: "model.supports_vision", label: "Model can see images", control: toggle },
        ],
      },
      {
        title: "llama.cpp",
        fields: [
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
          { key: "ports.client", label: "Web UI", control: num(1, 65535, 1) },
        ],
      },
    ],
  },
  {
    id: "storage",
    title: "Storage",
    description: "Where Atlas keeps what it generates. Paths are relative to the application folder.",
    groups: [
      {
        title: "Paths",
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
export const HIDDEN = new Set(["skills.disabled", "memory.enabled", "tools.interventions", "tools.documents"])

export function describedKeys(): Set<string> {
  return new Set(SECTIONS.flatMap((s) => s.groups.flatMap((g) => g.fields.map((f) => f.key))))
}
