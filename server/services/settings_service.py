"""Settings as the running backend sees them: saved values merged with what
the running servers were started with."""


from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.config import paths
from agent.config.settings import (
    Settings,
    parse_settings,
    restart_tier_values,
    set_path,
)
from server.state import Atlas

# ---------------------------------------------------------------- helpers --


def _live_settings(on_disk: dict[str, Any], boot: Settings) -> Settings:
    """The file's LIVE values, with RESTART values held at what the process started with."""
    merged = json.loads(json.dumps(on_disk))
    for key, value in restart_tier_values(boot.model_dump(mode="json")).items():
        set_path(merged, key, value)
    return parse_settings(merged)


def _launched_restart_values(state: Atlas) -> dict[str, Any]:
    """What the running servers were started with.

    launched.json when the CLI wrote one (its `restart_settings` block is flat,
    `{"model.path": ...}`), otherwise this process's own start-up values.
    """
    launched = Path(os.environ.get("ATLAS_LAUNCHED") or paths.ROOT / "launched.json")
    if launched.is_file():
        try:
            flat = json.loads(launched.read_text(encoding="utf-8")).get("restart_settings")
            if isinstance(flat, dict) and flat:
                return flat
        except (OSError, json.JSONDecodeError):
            pass
    return restart_tier_values(state.boot.model_dump(mode="json"))


__all__ = []
