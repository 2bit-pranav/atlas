"""Settings: the single source of truth (spec sections 4 and 1a).

`settings.json` is read, validated, and split into two tiers:

- **restart** - read once at launch and baked into the spawned llama-server.
  Changing one requires a restart.
- **live** - read fresh for every turn. A run snapshots the resolved live
  values, so a run is reproducible even if the file changes mid-flight. This
  is why the agent is rebuilt on every turn rather than cached.

Every new knob is added here first, then read by exactly one manager in
`agent/core/`. A manager never parses the file itself.

What was removed, and why: the previous schema had `ingest`, `ingest.vlm`,
`ingest.docling`, `context` and `results`. Documents are read through skills
now (section L5), and no VLM pipeline is configured, so those keys had no
consumer. Leaving them would have meant settings that silently do nothing.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Tier(str, Enum):
    """When a setting takes effect. See the module docstring."""

    RESTART = "restart"
    LIVE = "live"


class StrictModel(BaseModel):
    """Refuse unknown keys.

    A typo in `settings.json` is otherwise silently ignored, and the symptom
    is a behaviour that does not change no matter what you set.
    """

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- model ----


class ModelSettings(StrictModel):
    """The local model and the llama-server that serves it."""

    path: str
    mmproj_path: str = ""
    name: str = "local"
    context_size: int = Field(default=32768, gt=0)
    gpu_layers: str | int = "all"
    batch_size: int = Field(default=2048, gt=0)
    ubatch_size: int = Field(default=512, gt=0)
    threads: int = Field(default=6, gt=0)
    flash_attention: bool = True
    jinja: bool = True
    reasoning: str = "auto"
    #: One slot. Atlas runs a single agent with a single llama-server, and
    #: more slots only divide the same context window between parallel
    #: requests we never make.
    parallel_slots: int = Field(default=1, gt=0)
    supports_thinking: bool = True
    supports_vision: bool = True


class PortSettings(StrictModel):
    llama: int = 8080
    #: 8000 per design.md. The previous build used 8760; changed deliberately.
    backend: int = 8000
    client: int = 5173


class SamplingSettings(StrictModel):
    """Sent to the model on every request.

    Penalties act on the tokens being generated, so they change the *wording* of
    an answer, not its approach. What makes a retry genuinely different lives in
    `retry` instead.
    """

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    top_k: int = Field(default=40, ge=0)
    min_p: float = Field(default=0.05, ge=0.0, le=1.0)
    max_tokens: int = Field(default=2048, gt=0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    repeat_penalty: float = Field(default=1.0, gt=0.0)
    #: The UI's thinking toggle is a boolean only. llama.cpp supports an effort
    #: or budget for reasoning, but the per-request field for those was not
    #: documented, and ON/OFF is what we can verify.
    thinking: bool = False


class LlamaCppSettings(StrictModel):
    binary: str = "llama"
    subcommand: str = "serve"
    extra_args: list[str] = Field(default_factory=list)


# --------------------------------------------------------------- agents ----


class BuiltinToolSettings(StrictModel):
    """Which of the harness's built-in tools the agent gets, one switch each.

    Not cosmetic. Every tool schema costs prompt tokens on a 32k window, and a
    smaller set is also a safety control: dropping `shell` removes the ability
    to run anything at all -- including every skill script.
    """

    read: bool = True
    write: bool = True
    edit: bool = True
    shell: bool = True
    web_fetch: bool = False
    subagent: bool = False


class ToolsSettings(StrictModel):
    builtin: BuiltinToolSettings = Field(default_factory=BuiltinToolSettings)
    #: Ask before running a shell command. Off for now because there is no
    #: frontend to show the prompt; revisit with the UI (design.md L5).
    interventions: bool = False


class SkillSettings(StrictModel):
    dir: str = "skills"
    #: Skill folder names to switch off. Every other discovered skill is on, so
    #: a newly installed skill works without a second step. An unknown name is
    #: ignored: it usually means the skill was deleted after being disabled.
    disabled: list[str] = Field(default_factory=list)


class McpSettings(StrictModel):
    """MCP servers, in the standard `mcpServers` JSON format.

    Kept in its own file rather than inside settings.json because that format is
    what every MCP server's README shows: a block can be pasted in unchanged.
    """

    #: Relative to the application root.
    config: str = "mcp.json"
    #: Seconds to wait for one server to start and list its tools.
    startup_timeout: float = Field(default=30.0, gt=0)


class MemorySettings(StrictModel):
    """Long-term memory (design.md 1a, T3.7).

    **Hard-wired off.** This is not merely a default we might revisit: with a
    `Model` instance the harness reuses that same model to distil facts, and
    extraction runs in a background task whose failure is swallowed -- so a
    broken extractor is indistinguishable from an isolated one. Worse, the
    store is a flat directory of `<slug>.md` files with no session, chat or
    branch in the key, and it is injected on every turn. Branch isolation and
    long-term memory are structurally incompatible; `restore_snapshot` rewinds
    the message list and cannot touch the store.

    Enabling this later needs a real design (scope memory per chat, or filter
    by branch), not just flipping this flag.
    """

    enabled: bool = False

    @model_validator(mode="after")
    def _must_stay_off(self) -> "MemorySettings":
        if self.enabled:
            raise ValueError(
                "memory.enabled=true is not supported yet: the file memory store "
                "is not scoped to a chat or a branch, so facts written in one "
                "branch are injected into every other branch on every turn. "
                "Branch isolation is guaranteed only while this is false."
            )
        return self


class RetrySettings(StrictModel):
    """What makes a retried answer genuinely different from the one before it.

    A retry restores the same state and asks the same question, so on its own
    it gets a near-copy: the sampler is the only thing that changed, and a small
    model at a moderate temperature follows the same path. Three levers, in
    order of effect:

    1. `show_previous` -- the model is told what the earlier versions said and
       asked for a different approach. This is the only lever that changes the
       *reasoning*, not just the wording. The hint is stripped from history
       before the snapshot is saved, so follow-up turns never see it.
    2. `temperature_boost` and `presence_penalty` -- wider sampling for the
       retry only.
    3. A fresh random `seed`, so two retries never share a sampling path.
    """

    show_previous: bool = True
    #: How many earlier versions to quote, newest first.
    previous_limit: int = Field(default=2, ge=1, le=5)
    #: Characters quoted from each earlier version.
    previous_chars: int = Field(default=600, ge=100, le=4000)
    instructions: str = (
        "This question was already answered. Write a substantially different "
        "answer: take a different approach, structure or angle. Do not reword "
        "the earlier answer."
    )
    temperature_boost: float = Field(default=0.3, ge=0.0, le=1.0)
    presence_penalty: float = Field(default=0.6, ge=-2.0, le=2.0)
    new_seed: bool = True


class ResilienceSettings(StrictModel):
    """How a run recovers from failures without a human (agent/core/resilience.py).

    Built on Strands' own hooks rather than on prompt text: a 2B model does not
    reliably follow "retry on failure", but a hook always runs.
    """

    #: Total attempts per model call when llama-server errors or returns nothing.
    model_attempts: int = Field(default=3, ge=1, le=10)
    #: Seconds between model attempts. Local, so no exponential backoff.
    model_retry_delay: float = Field(default=1.0, ge=0.0, le=30.0)
    #: Re-runs of a tool that raised (crashed), as opposed to one that returned
    #: an error. A crash is usually transient; a returned error is not.
    tool_crash_retries: int = Field(default=1, ge=0, le=5)
    #: Failed tool calls per turn after which the model is told to stop trying
    #: and explain the failure instead.
    tool_failure_limit: int = Field(default=3, ge=1, le=10)
    #: When the model gives up straight after a failed tool call, re-invoke it
    #: once with the failure in front of it.
    nudge_after_failure: bool = True


class SessionSettings(StrictModel):
    """Where Strands writes snapshots. Relative to `paths.data_dir`."""

    dir: str = "sessions"


class ContextSettings(StrictModel):
    """Context trimming, L6. Configuration only, for now.

    The harness's own `context_manager` is disabled because its `agentic` mode
    adds a `retrieve_context` tool and offloads tool results to a stash, which
    is the same family of cross-branch leak as memory. Trimming proper is L6;
    until then `NullConversationManager` keeps history intact and a long chat
    will eventually hit the window.
    """

    #: Disabled until L6 picks and measures a conversation manager.
    conversation_manager: str = Field(
        default="null", pattern="^(null|sliding|summarizing)$"
    )
    window: int = Field(default=32768, gt=0)
    prune_trigger_ratio: float = Field(default=0.75, gt=0.0, lt=1.0)
    prune_target_ratio: float = Field(default=0.50, gt=0.0, lt=1.0)
    generation_reserve: int = Field(default=8000, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "ContextSettings":
        if self.prune_target_ratio >= self.prune_trigger_ratio:
            raise ValueError(
                "context.prune_target_ratio must be below context.prune_trigger_ratio "
                f"({self.prune_target_ratio} >= {self.prune_trigger_ratio})"
            )
        return self


class PathsSettings(StrictModel):
    #: Everything Atlas generates: the chat database, Strands snapshots, and
    #: each chat's uploads and workspace. Relative to the application root, and
    #: dot-prefixed so it reads as state rather than source.
    data_dir: str = ".data"


class Settings(StrictModel):
    model: ModelSettings
    ports: PortSettings = Field(default_factory=PortSettings)
    sampling: SamplingSettings = Field(default_factory=SamplingSettings)
    llamacpp: LlamaCppSettings = Field(default_factory=LlamaCppSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    skills: SkillSettings = Field(default_factory=SkillSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
    #: Appended to Strands' harness system prompt, not a replacement for it.
    #: Measured: `instructions=` appends, so the harness guidance is retained.
    system_prompt: str = ""


#: The only place that knows which key is which tier. `test_settings_tiers.py`
#: asserts this covers every leaf of the schema, so a new setting cannot
#: silently escape tiering.
TIERS: dict[str, Tier] = {
    "model.path": Tier.RESTART,
    "model.mmproj_path": Tier.RESTART,
    "model.name": Tier.RESTART,
    "model.context_size": Tier.RESTART,
    "model.gpu_layers": Tier.RESTART,
    "model.batch_size": Tier.RESTART,
    "model.ubatch_size": Tier.RESTART,
    "model.threads": Tier.RESTART,
    "model.flash_attention": Tier.RESTART,
    "model.jinja": Tier.RESTART,
    "model.reasoning": Tier.RESTART,
    "model.parallel_slots": Tier.RESTART,
    "model.supports_thinking": Tier.RESTART,
    "model.supports_vision": Tier.RESTART,
    "ports.llama": Tier.RESTART,
    "ports.backend": Tier.RESTART,
    "ports.client": Tier.RESTART,
    "llamacpp.binary": Tier.RESTART,
    "llamacpp.subcommand": Tier.RESTART,
    "llamacpp.extra_args": Tier.RESTART,
    "sampling.temperature": Tier.LIVE,
    "sampling.top_p": Tier.LIVE,
    "sampling.top_k": Tier.LIVE,
    "sampling.min_p": Tier.LIVE,
    "sampling.max_tokens": Tier.LIVE,
    "sampling.presence_penalty": Tier.LIVE,
    "sampling.frequency_penalty": Tier.LIVE,
    "sampling.repeat_penalty": Tier.LIVE,
    "sampling.thinking": Tier.LIVE,
    "tools.builtin.read": Tier.LIVE,
    "tools.builtin.write": Tier.LIVE,
    "tools.builtin.edit": Tier.LIVE,
    "tools.builtin.shell": Tier.LIVE,
    "tools.builtin.web_fetch": Tier.LIVE,
    "tools.builtin.subagent": Tier.LIVE,
    "tools.interventions": Tier.LIVE,
    "skills.dir": Tier.LIVE,
    "skills.disabled": Tier.LIVE,
    "mcp.config": Tier.RESTART,
    "mcp.startup_timeout": Tier.LIVE,
    "memory.enabled": Tier.RESTART,
    "retry.show_previous": Tier.LIVE,
    "retry.previous_limit": Tier.LIVE,
    "retry.previous_chars": Tier.LIVE,
    "retry.instructions": Tier.LIVE,
    "retry.temperature_boost": Tier.LIVE,
    "retry.presence_penalty": Tier.LIVE,
    "retry.new_seed": Tier.LIVE,
    "resilience.model_attempts": Tier.LIVE,
    "resilience.model_retry_delay": Tier.LIVE,
    "resilience.tool_crash_retries": Tier.LIVE,
    "resilience.tool_failure_limit": Tier.LIVE,
    "resilience.nudge_after_failure": Tier.LIVE,
    "session.dir": Tier.RESTART,
    "context.conversation_manager": Tier.LIVE,
    "context.window": Tier.RESTART,
    "context.prune_trigger_ratio": Tier.LIVE,
    "context.prune_target_ratio": Tier.LIVE,
    "context.generation_reserve": Tier.LIVE,
    "paths.data_dir": Tier.RESTART,
    "system_prompt": Tier.LIVE,
}


# ------------------------------------------------------------- helpers ----


def get_path(data: Any, dotted: str) -> Any:
    """Read a dotted key, returning None if any part is missing."""
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Nested dict -> {"a.b": value}."""
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and value:
                out.update(flatten(value, path))
            else:
                out[path] = value
    return out


def iter_leaf_paths(data: Any, prefix: str = "") -> Iterator[str]:
    for key in flatten(data, prefix):
        yield key


def restart_tier_values(data: dict[str, Any]) -> dict[str, Any]:
    return {k: get_path(data, k) for k, t in TIERS.items() if t is Tier.RESTART}


def live_tier_values(data: dict[str, Any]) -> dict[str, Any]:
    return {k: get_path(data, k) for k, t in TIERS.items() if t is Tier.LIVE}


def changed_restart_keys(
    current: dict[str, Any], launched_flat: dict[str, Any]
) -> dict[str, Any]:
    """Restart-tier keys that differ from what the running servers were built with.

    `current` is the nested settings dict; `launched_flat` is the *flat*
    `restart_settings` block of launched.json (`{"model.path": ...}`). They
    used to be compared with the same nested walk, which found nothing in the
    flat dict, so every restart key always counted as changed.

    A key absent from `launched_flat` is not reported: it was added to the
    schema after that launch, and its default is what the launch ran with.
    """
    return {
        key: now
        for key, now in restart_tier_values(current).items()
        if key in launched_flat and launched_flat[key] != now
    }


class SettingsError(Exception):
    """Invalid `settings.json`. The message is shown to the user verbatim."""


def parse_settings(data: Any) -> Settings:
    try:
        return Settings.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - re-raised as our own type
        raise SettingsError(f"invalid settings.json:\n{exc}") from exc


def set_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    """Write a dotted key into a nested dict, creating parents as needed."""
    node = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def write_settings(path: Path, data: dict[str, Any]) -> None:
    """Validate, then replace the file atomically.

    Validated first so an invalid patch never reaches disk, and written through
    a temp file so a crash mid-write cannot leave unparseable JSON behind.
    """
    parse_settings(data)
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def load_settings(path: Path) -> Settings:
    p = Path(path)
    if not p.exists():
        raise SettingsError(
            f"no settings file at {p}. Copy settings.example.json to settings.json."
        )
    try:
        return parse_settings(json.loads(p.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{p} is not valid JSON: {exc}") from exc


__all__ = [
    "BuiltinToolSettings",
    "ContextSettings",
    "LlamaCppSettings",
    "McpSettings",
    "MemorySettings",
    "ModelSettings",
    "PortSettings",
    "ResilienceSettings",
    "RetrySettings",
    "SamplingSettings",
    "SessionSettings",
    "Settings",
    "SettingsError",
    "SkillSettings",
    "StrictModel",
    "TIERS",
    "Tier",
    "ToolsSettings",
    "changed_restart_keys",
    "flatten",
    "get_path",
    "iter_leaf_paths",
    "live_tier_values",
    "load_settings",
    "parse_settings",
    "restart_tier_values",
    "set_path",
    "write_settings",
]