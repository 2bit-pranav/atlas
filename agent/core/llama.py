"""Which local models exist, and the files llama-server is started with.

llama-server serves one model, started with `-m <gguf> [--mmproj <file>]`.
The models live in one folder (`model.dir`, default `llm/`), one subfolder
each, so the Settings page can offer them by name and a downloaded model only
has to land in its own folder:

    llm/gemma/unsloth_e2b_qat.gguf    -> model "gemma"
    llm/gemma/mmproj-F16.gguf         -> its image/audio projector
    llm/notes.gguf                    -> model "notes" (a loose file, no mmproj)

Changing model means restarting llama-server (Settings > Restart). Router
mode, which loads models on demand without a restart, was tried and dropped:
each switch still cost a full load plus re-reading the prompt, and a model
that did not fit the GPU failed only when first used (docs/decisions.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core import paths
from agent.core.settings import Settings


#: Set by `atlas start` for the backend: the per-launch key llama-server was
#: started with (`--api-key`). Without it any web page could use the model
#: through 127.0.0.1, since llama-server allows every origin.
KEY_ENV = "ATLAS_LLAMA_KEY"


def auth_headers() -> dict[str, str]:
    key = os.environ.get(KEY_ENV)
    return {"Authorization": f"Bearer {key}"} if key else {}


class ModelError(RuntimeError):
    """The configured model is not in the models folder."""


@dataclass
class LocalModel:
    name: str
    gguf: Path
    mmproj: Path | None

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "file": self.gguf.name, "mmproj": self.mmproj.name if self.mmproj else None,
                "bytes": self.gguf.stat().st_size}


def _is_mmproj(path: Path) -> bool:
    return "mmproj" in path.name.lower()


def discover(folder: Path) -> list[LocalModel]:
    """Every model in `folder`: a subfolder with a .gguf, or a loose .gguf."""
    if not folder.is_dir():
        return []
    found: list[LocalModel] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            ggufs = sorted(entry.glob("*.gguf"))
            weights = [g for g in ggufs if not _is_mmproj(g)]
            if not weights:
                continue
            # Several weights in one folder (quants): the largest is the model.
            gguf = max(weights, key=lambda g: g.stat().st_size)
            mmproj = next((g for g in ggufs if _is_mmproj(g)), None)
            found.append(LocalModel(entry.name, gguf, mmproj))
        elif entry.suffix.lower() == ".gguf" and not _is_mmproj(entry):
            found.append(LocalModel(entry.stem, entry, None))
    return found


def current(settings: Settings) -> LocalModel:
    """The model settings name, or ModelError listing what does exist."""
    models = discover(paths.models_dir(settings))
    for model in models:
        if model.name == settings.model.name:
            return model
    known = ", ".join(m.name for m in models) or "none"
    raise ModelError(f"no model {settings.model.name!r} in {paths.models_dir(settings)} (found: {known})")


__all__ = ["KEY_ENV", "LocalModel", "ModelError", "auth_headers", "current", "discover"]
