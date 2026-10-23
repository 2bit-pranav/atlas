"""The command lines of the processes Atlas starts, built from settings."""

from __future__ import annotations

import os
import shutil
import sys

from agent.core import llama
from agent.core.settings import Settings


def build_llamacpp_args(settings: Settings, api_key: str | None = None) -> list[str]:
    """llama-server with the model chosen in Settings. Raises llama.ModelError."""
    model = settings.model
    args: list[str] = [settings.llamacpp.binary]
    if settings.llamacpp.subcommand:  # `llama serve` rather than `llama-server`
        args.append(settings.llamacpp.subcommand)

    chosen = llama.current(settings)
    args += ["-m", str(chosen.gguf), "--alias", chosen.name]
    if chosen.mmproj is not None:
        args += ["--mmproj", str(chosen.mmproj)]

    gpu_layers = model.gpu_layers
    args += [
        "--no-ui",
        "-c", str(model.context_size),
        "-ngl", str(gpu_layers),
        "-b", str(model.batch_size), "-ub", str(model.ubatch_size),
    ]
    if model.threads:
        args += ["-t", str(model.threads)]
    # Always pass the port: llama.cpp's own default is due to change.
    args += ["--host", "127.0.0.1", "--port", str(settings.ports.llama)]
    args += ["-np", str(model.parallel_slots), "-fa", "on" if model.flash_attention else "off"]
    if model.jinja:
        args.append("--jinja")
    args += ["--reasoning", model.reasoning]
    if api_key:
        args += ["--api-key", api_key]
    args += list(settings.llamacpp.extra_args)
    return args


def build_backend_args(settings: Settings) -> list[str]:
    """The FastAPI backend. Never `--reload` (see server/main.py)."""
    return [sys.executable, "-m", "uvicorn", "server.main:app",
            "--host", "127.0.0.1", "--port", str(settings.ports.backend)]


def npm() -> str | None:
    return shutil.which("npm.cmd" if os.name == "nt" else "npm")


def build_vite_args(settings: Settings) -> list[str]:
    """The Vite dev server with hot reload, for `atlas start --dev`."""
    exe = npm()
    if not exe:
        raise FileNotFoundError("npm is not on PATH; `--dev` needs Node.js")
    return [exe, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(settings.ports.client)]


def describe_args(args: list[str]) -> str:
    shown = ["***" if i and args[i - 1] == "--api-key" else a for i, a in enumerate(args)]
    return " ".join(f'"{a}"' if " " in a else a for a in shown)


__all__ = ["build_backend_args", "build_llamacpp_args", "build_vite_args", "describe_args", "npm"]
