"""The llama.cpp model for a turn, with its sampling settings; the summarizer model."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.config.settings import Settings
from agent.model.llamacpp import AtlasLlamaCppModel


@dataclass
class RetryPlan:
    """What a retried turn does differently. `None` for every other turn."""

    #: Final answer text of the earlier versions, newest first.
    previous: list[str] = field(default_factory=list)


def build_model(
    settings: Settings,
    *,
    thinking: bool,
    retry: RetryPlan | None = None,
    observer: Callable[[dict[str, Any]], None] | None = None,
) -> AtlasLlamaCppModel:
    """The model for this turn.

    Sampling comes from settings every time, so a temperature change applies to
    the next turn rather than after a restart. A retry widens it (see
    `RetrySettings`): higher temperature, a presence penalty, a fresh seed.
    """
    s = settings.sampling
    params: dict[str, Any] = {
        "cache_prompt": True,
        "temperature": s.temperature,
        "top_p": s.top_p,
        "top_k": s.top_k,
        "min_p": s.min_p,
        "repeat_penalty": s.repeat_penalty,
        "max_tokens": s.max_tokens,
    }
    if s.presence_penalty:
        params["presence_penalty"] = s.presence_penalty
    if s.frequency_penalty:
        params["frequency_penalty"] = s.frequency_penalty

    if retry is not None:
        r = settings.retry
        params["temperature"] = min(2.0, s.temperature + r.temperature_boost)
        if r.presence_penalty:
            params["presence_penalty"] = r.presence_penalty
        if r.new_seed:
            params["seed"] = random.randrange(1, 2**31 - 1)

    return AtlasLlamaCppModel(
        base_url=f"http://127.0.0.1:{settings.ports.llama}",
        model_id=settings.model.name,
        enable_thinking=thinking,
        context_window_limit=settings.context.window or settings.model.context_size,
        params=params,
        # Timings on every chunk, so the context meter and tokens/s move while
        # the answer is still being written rather than jumping at the end.
        extra_body={"timings_per_token": True},
        observer=observer,
    )


__all__ = ["RetryPlan", "build_model"]
