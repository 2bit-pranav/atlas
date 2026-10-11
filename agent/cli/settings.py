"""Settings: the single source of truth (spec section 4).

``settings.json`` is read, validated and split into two tiers:

* **restart** - read once at launch, baked into the spawned llama-server and the
  backend process. Changing one requires a restart; the UI writes the file and
  shows "restart required".
* **live** - read fresh for every run. A run snapshots the resolved live values
  so a run is reproducible even if the file changes mid-flight.

The tier registry below is the only place that knows which key is which tier.
``test_settings_tiers.py`` asserts it covers every leaf of the schema, so a new
setting cannot silently escape tiering.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from agent.run.prompt import SYSTEM_PROMPT


class Tier(str, Enum):
    RESTART = "restart"
    LIVE = "live"


class DoclingPipeline(str, Enum):
    STANDARD = "standard"
    VLM = "vlm"
    AUTO = "auto"


class StrictModel(BaseModel):
    """Base: reject unknown keys so a typo fails fast instead of being ignored."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------- restart


class ModelSettings(StrictModel):
    path: str = Field(description="GGUF path passed to llama-server -m")
    mmproj_path: str | None = Field(
        default=None, description="Vision projector; required when supports_vision"
    )
    name: str | None = Field(default=None, description="Alias recorded in launched.json")
    context_size: int = Field(default=32768, gt=0, le=1_048_576)
    gpu_layers: int | str = Field(
        default="auto",
        description="-ngl. 'auto' offloads as much as fits and falls back to CPU when "
        "there is no GPU, so it is the portable default; 'all' forces every layer. "
        "Set 0 to force CPU. Larger values do not change generation speed much - "
        "generation is memory-bandwidth bound, not compute bound.",
    )
    device: str = Field(
        default="auto",
        description="--device. 'auto' omits the flag so llama.cpp picks the best "
        "backend (CUDA/Vulkan) for this machine. Set e.g. 'Vulkan1' to pin one.",
    )
    batch_size: int = Field(
        default=2048, gt=0, description="-b; prompt processing batch, larger preflills faster"
    )
    ubatch_size: int = Field(default=512, gt=0, description="-ub; micro-batch, must divide -b")
    threads: int | None = Field(
        default=None,
        gt=0,
        description="-t generation threads. None lets llama.cpp pick (physical cores). "
        "Generation is memory bound, so this matters less than keeping the model on the GPU.",
    )
    flash_attention: bool = Field(default=True, description="-fa on")
    jinja: bool = Field(default=True, description="-jinja; required for the chat template")
    reasoning: str = Field(
        default="auto",
        description="--reasoning on|off|auto. This is NOT the same as our per-request "
        "`thinking` setting: it decides whether the chat template may emit thought "
        "tags at all, and auto-detection is what selects the deepseek format, i.e. "
        "the mode that populates message.reasoning_content. Our enable_thinking "
        "kwarg (S1) then switches thinking per request inside that. Verified "
        "necessary: with reasoning extraction disabled, S2's reasoning passthrough "
        "has nothing to read.",
    )
    parallel_slots: int = Field(
        default=1,
        ge=1,
        description="-np. Atlas runs one run at a time, so 1 slot is right: with N "
        "slots llama.cpp splits -c across them, so 4 slots on a 32k window would "
        "give ~8k per slot. Never assume per-slot context equals context_size (S25).",
    )
    supports_thinking: bool = Field(default=True)
    supports_vision: bool = Field(default=False)

    @model_validator(mode="after")
    def _batch_split(self) -> ModelSettings:
        if self.ubatch_size > self.batch_size:
            raise ValueError(
                f"model.ubatch_size ({self.ubatch_size}) cannot exceed "
                f"model.batch_size ({self.batch_size})"
            )
        if self.reasoning not in ("on", "off", "auto"):
            raise ValueError(
                f"model.reasoning must be one of on/off/auto, got {self.reasoning!r}"
            )
        return self


class PortSettings(StrictModel):
    llama: int = Field(default=8080, ge=1, le=65535)
    backend: int = Field(default=8000, ge=1, le=65535)
    client: int = Field(default=5173, ge=1, le=65535)
    ingest_vlm: int = Field(default=8081, ge=1, le=65535)

    @model_validator(mode="after")
    def _unique(self) -> PortSettings:
        seen: dict[int, str] = {}
        for name in ("llama", "backend", "client", "ingest_vlm"):
            value = getattr(self, name)
            if value in seen:
                raise ValueError(f"ports.{name} and ports.{seen[value]} are both {value}")
            seen[value] = name
        return self


class EmbeddingSettings(StrictModel):
    enabled: bool = True
    model: str = "BAAI/bge-small-en-v1.5"
    dimensions: int = Field(default=384, gt=0)


class IngestVlmSettings(StrictModel):
    model_path: str = ""
    gpu_layers: int = Field(
        default=0, ge=0, description="CPU by default so Gemma keeps the VRAM (section 3)"
    )


class DoclingSettings(StrictModel):
    pipeline: DoclingPipeline = DoclingPipeline.AUTO
    pages_per_progress_report: int = Field(default=1, ge=1)


class IngestSettings(StrictModel):
    device: str = "cpu"
    vlm: IngestVlmSettings = Field(default_factory=IngestVlmSettings)
    docling: DoclingSettings = Field(default_factory=DoclingSettings)


# ------------------------------------------------------------------------ live


class SamplingSettings(StrictModel):
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    top_k: int = Field(default=40, ge=0)
    temperature: float = Field(default=0.7, ge=0.0)
    max_tokens: int = Field(
        default=2048,
        gt=0,
        description="Leave headroom when thinking is on: reasoning consumes the "
        "same window (section 10, S26).",
    )
    thinking: bool = Field(
        default=False, description="Default for the per-message toggle; sent explicitly on every request"
    )


class ContextSettings(StrictModel):
    """Budget regions from section 10, in tokens."""

    fixed_reserve: int = Field(default=5000, gt=0)
    pinned_reserve: int = Field(default=3000, gt=0)
    history_reserve: int = Field(default=5000, gt=0)
    rolling_reserve: int = Field(default=10000, gt=0)
    generation_reserve: int = Field(default=8000, gt=0)
    prune_trigger_ratio: float = Field(
        default=0.75, gt=0.0, lt=1.0, description="Prune in batches once the prompt passes this"
    )
    prune_target_ratio: float = Field(
        default=0.50, gt=0.0, lt=1.0, description="Compact down to this, to keep the prefix byte-stable"
    )

    @model_validator(mode="after")
    def _ordered(self) -> ContextSettings:
        if self.prune_target_ratio >= self.prune_trigger_ratio:
            raise ValueError(
                "context.prune_target_ratio must be below context.prune_trigger_ratio "
                f"({self.prune_target_ratio} >= {self.prune_trigger_ratio})"
            )
        return self

    def prompt_budget(self, window: int) -> int:
        return window - self.generation_reserve


class ResultSettings(StrictModel):
    passthrough_tokens: int = Field(default=400, gt=0, description="Below this a result is shown inline")
    max_inline_tokens: int = Field(default=1500, gt=0, description="Hard cap on anything shown inline")
    display_budget_tokens: int = Field(default=400, gt=0, description="Query results shown if they fit")
    max_tool_iterations: int = Field(default=20, gt=0)
    max_argument_tokens: int = Field(default=800, gt=0, description="Above this, pass data by reference")

    @model_validator(mode="after")
    def _ordered(self) -> ResultSettings:
        if self.passthrough_tokens > self.max_inline_tokens:
            raise ValueError(
                "results.passthrough_tokens cannot exceed results.max_inline_tokens "
                f"({self.passthrough_tokens} > {self.max_inline_tokens})"
            )
        return self


class SkillsSettings(StrictModel):
    dirs: list[str] = Field(default_factory=lambda: ["skills"])
    pinned_token_cap: int = Field(default=2000, gt=0)
    max_tool_schema_tokens: int = Field(default=2000, gt=0)


# ----------------------------------------------------------------------- root


class LlamaCppSettings(StrictModel):
    """Which binary to spawn, and the escape hatch for unmodelled flags."""

    binary: str = Field(
        default="llama",
        description="llama.cpp CLI. `llama serve` is the modern entrypoint; the older "
        "`llama-server` name may not exist on a current install.",
    )
    subcommand: str = Field(default="serve", description="Subcommand to run; empty for none")
    extra_args: list[str] = Field(default_factory=list)
    built_in_tools: bool = Field(
        default=False,
        description="--tools. DANGER: this is llama.cpp's own agent toolkit "
        "(read_file, write_file, exec_shell_command, get_info), NOT tool-call "
        "parsing. Atlas registers its own tools through Strands and keeps raw paths "
        "away from the model, so this stays off. Enabling it hands the model a shell.",
    )


class Settings(StrictModel):
    model: ModelSettings
    ports: PortSettings = Field(default_factory=PortSettings)
    llamacpp: LlamaCppSettings = Field(default_factory=LlamaCppSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    sampling: SamplingSettings = Field(default_factory=SamplingSettings)
    context: ContextSettings = Field(default_factory=ContextSettings)
    results: ResultSettings = Field(default_factory=ResultSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    system_prompt: str = SYSTEM_PROMPT

    @field_validator("model")
    @classmethod
    def _vision_needs_mmproj(cls, model: ModelSettings) -> ModelSettings:
        if model.supports_vision and not model.mmproj_path:
            raise ValueError(
                "model.supports_vision is true but model.mmproj_path is empty; "
                "llama-server needs --mmproj for image input"
            )
        return model

    # ------------------------------------------------------------- snapshot --

    def snapshot(self) -> dict[str, Any]:
        """Resolved values recorded on a run (section 4).

        Includes the restart tier as well: it is fixed for the life of the
        launch, and recording it makes a run reproducible from the row alone.
        """
        return self.model_dump(mode="json")


# ---------------------------------------------------------------- tier table --
#
# The one source of truth for tiering. Anything not listed here is a bug;
# tests/test_settings_tiers.py asserts coverage against the schema.

TIERS: dict[str, Tier] = {
    "model.path": Tier.RESTART,
    "model.mmproj_path": Tier.RESTART,
    "model.name": Tier.RESTART,
    "model.context_size": Tier.RESTART,
    "model.gpu_layers": Tier.RESTART,
    "model.device": Tier.RESTART,
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
    "ports.ingest_vlm": Tier.RESTART,
    "llamacpp.binary": Tier.RESTART,
    "llamacpp.subcommand": Tier.RESTART,
    "llamacpp.extra_args": Tier.RESTART,
    "llamacpp.built_in_tools": Tier.RESTART,
    "embedding.enabled": Tier.RESTART,
    "embedding.model": Tier.RESTART,
    "embedding.dimensions": Tier.RESTART,
    "ingest.vlm.model_path": Tier.RESTART,
    "ingest.vlm.gpu_layers": Tier.RESTART,
    "ingest.device": Tier.LIVE,
    "ingest.docling.pipeline": Tier.LIVE,
    "ingest.docling.pages_per_progress_report": Tier.LIVE,
    "sampling.top_p": Tier.LIVE,
    "sampling.top_k": Tier.LIVE,
    "sampling.temperature": Tier.LIVE,
    "sampling.max_tokens": Tier.LIVE,
    "sampling.thinking": Tier.LIVE,
    "context.fixed_reserve": Tier.LIVE,
    "context.pinned_reserve": Tier.LIVE,
    "context.history_reserve": Tier.LIVE,
    "context.rolling_reserve": Tier.LIVE,
    "context.generation_reserve": Tier.LIVE,
    "context.prune_trigger_ratio": Tier.LIVE,
    "context.prune_target_ratio": Tier.LIVE,
    "results.passthrough_tokens": Tier.LIVE,
    "results.max_inline_tokens": Tier.LIVE,
    "results.display_budget_tokens": Tier.LIVE,
    "results.max_tool_iterations": Tier.LIVE,
    "results.max_argument_tokens": Tier.LIVE,
    "skills.dirs": Tier.LIVE,
    "skills.pinned_token_cap": Tier.LIVE,
    "skills.max_tool_schema_tokens": Tier.LIVE,
    "system_prompt": Tier.LIVE,
}


def get_path(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        node = node[part]
    return node


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Nested dict -> {"model.context_size": 32768, ...}, matching TIERS keys."""
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                out.update(flatten(value, path))
            else:
                out[path] = value
    else:
        out[prefix] = data
    return out


def iter_leaf_paths(data: Any, prefix: str = "") -> Iterator[str]:
    yield from flatten(data, prefix)


# ------------------------------------------------------------------- loading --


class SettingsError(Exception):
    """Raised for any unusable settings file, with every problem listed."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(["invalid settings.json:"] + [f"  - {p}" for p in problems]))


def parse_settings(data: Any) -> Settings:
    """Validate raw JSON into Settings, raising one readable error for all problems."""
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"]) or "<root>"
            problems.append(f"{where}: {err['msg']}")
        raise SettingsError(problems) from exc


def load_settings(path: Path) -> Settings:
    """Read and validate settings.json. Fails fast with a clear message."""
    if not path.exists():
        raise SettingsError([f"no settings file at {path}"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsError([f"{path} is not valid JSON: {exc}"]) from exc
    return parse_settings(raw)


def restart_tier_values(data: dict[str, Any]) -> dict[str, Any]:
    flat = flatten(data)
    return {k: v for k, v in flat.items() if TIERS.get(k) is Tier.RESTART}


def live_tier_values(data: dict[str, Any]) -> dict[str, Any]:
    flat = flatten(data)
    return {k: v for k, v in flat.items() if TIERS.get(k) is Tier.LIVE}


def changed_restart_keys(current: dict[str, Any], launched: dict[str, Any]) -> dict[str, Any]:
    """Restart-tier keys whose value differs from what the running processes use.

    ``launched`` is the restart-tier slice written at launch. Keys added since
    launch count as changed.
    """
    return {
        key: value
        for key, value in restart_tier_values(current).items()
        if key not in launched or launched[key] != value
    }


def default_settings_template() -> dict[str, Any]:
    """A complete settings.json with every key present, for first run."""
    return Settings(
        model=ModelSettings(
            path="",
            name="",
            context_size=32768,
            gpu_layers=0,
            device="cpu",
            supports_thinking=True,
            supports_vision=False,
        )
    ).model_dump(mode="json")
