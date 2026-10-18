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

    `presence_penalty` and `frequency_penalty` bias a retried turn toward a
    different wording. Note what that does and does not buy: penalties act on
    tokens being generated, so they make a second attempt *differently worded*,
    not differently *reasoned*. Forcing a different approach is better served by
    restoring further back (see `regeneration.rewind_to`) or by the instruction
    in `regeneration.instructions`. Both are settings rather than behaviour, so
    the choice stays open until it is measured (T3.10).
    """

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    top_k: int = Field(default=40, ge=0)
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


class ToolGroupSettings(StrictModel):
    """Which built-in tool groups are on (design.md 1a).

    Not cosmetic. Every tool schema costs prompt tokens on a 32k window, and a
    smaller set is also a safety control: dropping `shell` removes the ability
    to run anything at all.
    """

    files: bool = True
    shell: bool = True
    web: bool = False
    subagents: bool = False


class ToolsSettings(StrictModel):
    groups: ToolGroupSettings = Field(default_factory=ToolGroupSettings)
    #: Ask before running a shell command. Off for now because there is no
    #: frontend to show the prompt; revisit with the UI (design.md L5).
    interventions: bool = False


class SkillSettings(StrictModel):
    dir: str = "skills"
    #: Skill folder names to enable. Empty means "all discovered". An unknown
    #: name is a startup error rather than a silent no-op, because a typo here
    #: looks exactly like "the skill does not work".
    enabled: list[str] = Field(default_factory=list)


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


class RegenerationSettings(StrictModel):
    """How a retry or an edit differs from the attempt it replaces.

    Both versions are always kept -- nothing is deleted (T3.9) -- so these only
    shape the *new* attempt.
    """

    #: `replace` rewrites the visible tail; `branch` keeps both and lets `<`/`>`
    #: switch. The tree supports both; this picks the default.
    mode: str = Field(default="branch", pattern="^(replace|branch)$")
    #: How far back a retry restores. `turn` = before the failed answer;
    #: `tool_result` = before the last tool result, which forces the model to
    #: re-derive the answer rather than re-read its own conclusion.
    rewind_to: str = Field(default="turn", pattern="^(turn|tool_result)$")
    #: Appended to the retried user turn, and deliberately kept OUTSIDE the
    #: snapshot so repeated retries cannot compound it.
    instructions: str = ""
    fresh_seed: bool = True


class SessionSettings(StrictModel):
    """Where Strands writes snapshots, and when Atlas adds one."""

    dir: str = "data/sessions"
    #: `append` is the only supported mode and is not configurable: snapshots
    #: written with `is_latest=False` are immutable and are never deleted, which
    #: is what makes retry, edit and `<`/`>` able to return to any earlier point.
    #: `delete_session` is never called.
    mode: str = Field(default="append", pattern="^append$")
    #: Capped, so a long conversation cannot fill the disk. Old snapshots are
    #: dropped oldest-first; the tree rows survive so a dropped id fails loudly
    #: rather than silently.
    max_snapshots: int = Field(default=500, gt=0)


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
    data_dir: str = "data"


class Settings(StrictModel):
    model: ModelSettings
    ports: PortSettings = Field(default_factory=PortSettings)
    sampling: SamplingSettings = Field(default_factory=SamplingSettings)
    llamacpp: LlamaCppSettings = Field(default_factory=LlamaCppSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    skills: SkillSettings = Field(default_factory=SkillSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    regeneration: RegenerationSettings = Field(default_factory=RegenerationSettings)
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
    "sampling.max_tokens": Tier.LIVE,
    "sampling.presence_penalty": Tier.LIVE,
    "sampling.frequency_penalty": Tier.LIVE,
    "sampling.repeat_penalty": Tier.LIVE,
    "sampling.thinking": Tier.LIVE,
    "tools.groups.files": Tier.LIVE,
    "tools.groups.shell": Tier.LIVE,
    "tools.groups.web": Tier.LIVE,
    "tools.groups.subagents": Tier.LIVE,
    "tools.interventions": Tier.LIVE,
    "skills.dir": Tier.LIVE,
    "skills.enabled": Tier.LIVE,
    "memory.enabled": Tier.RESTART,
    "regeneration.mode": Tier.LIVE,
    "regeneration.rewind_to": Tier.LIVE,
    "regeneration.instructions": Tier.LIVE,
    "regeneration.fresh_seed": Tier.LIVE,
    "session.dir": Tier.RESTART,
    "session.mode": Tier.RESTART,
    "session.max_snapshots": Tier.LIVE,
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
    current: dict[str, Any], launched: dict[str, Any]
) -> dict[str, Any]:
    """Restart-tier keys that differ from what the running servers were built with."""
    out: dict[str, Any] = {}
    for key in restart_tier_values(current):
        now, was = get_path(current, key), get_path(launched, key)
        if now != was:
            out[key] = now
    return out


class SettingsError(Exception):
    """Invalid `settings.json`. The message is shown to the user verbatim."""


def parse_settings(data: Any) -> Settings:
    try:
        return Settings.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - re-raised as our own type
        raise SettingsError(f"invalid settings.json:\n{exc}") from exc


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
    "ContextSettings",
    "LlamaCppSettings",
    "MemorySettings",
    "ModelSettings",
    "PortSettings",
    "RegenerationSettings",
    "SamplingSettings",
    "SessionSettings",
    "Settings",
    "SettingsError",
    "SkillSettings",
    "StrictModel",
    "TIERS",
    "Tier",
    "ToolGroupSettings",
    "ToolsSettings",
    "changed_restart_keys",
    "flatten",
    "get_path",
    "iter_leaf_paths",
    "live_tier_values",
    "load_settings",
    "parse_settings",
    "restart_tier_values",
]