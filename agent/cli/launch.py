"""
Command-line argument builders for Atlas managed processes.

Builds invocation arguments for:
  - llama-server (derived from `settings.json` model and llamacpp configurations)
  - FastAPI backend (server.main:app)
  - Vite frontend (npm run dev)
"""

from __future__ import annotations

import logging
import os
import shutil
import sys

from agent.core import paths
from agent.core.settings import Settings

logger = logging.getLogger(__name__)


def build_llamacpp_args(settings: Settings) -> list[str]:
    """Full argv for llama-server derived from restart-tier settings."""
    model = settings.model
    args: list[str] = [settings.llamacpp.binary]
    
    # adapt to llama-server vs llama serve 
    if settings.llamacpp.subcommand:
        args.append(settings.llamacpp.subcommand)

    # Router mode: every subfolder of the models folder is a model, its mmproj
    # found beside it; the flags below apply to each. One at a time, because
    # one GPU holds one model; the default is loaded once the router is up.
    args += ["--models-dir", str(paths.models_dir(settings)), "--models-max", "1"]

    args += ["--no-ui"] # skip webui permanently
    args += ["-c", str(model.context_size)]

    gpu_layers = model.gpu_layers
    args += ["-ngl", str(gpu_layers) if isinstance(gpu_layers, int) else gpu_layers]
    args += ["-b", str(model.batch_size), "-ub", str(model.ubatch_size)]

    if model.threads:
        args += ["-t", str(model.threads)]

    args += ["--host", "127.0.0.1", "--port", str(settings.ports.llama)]
    args += ["-np", str(model.parallel_slots)]
    args += ["-fa", "on" if model.flash_attention else "off"]

    if model.jinja:
        args.append("--jinja")

    args += ["--reasoning", model.reasoning]
    args += list(settings.llamacpp.extra_args)
    return args


def build_backend_args(settings: Settings) -> list[str]:
    """Argv for the FastAPI backend process."""
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "server.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.ports.backend),
    ]


def build_frontend_args(settings: Settings) -> list[str]:
    """Argv for the Vite frontend development server."""
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise FileNotFoundError("npm was not found on PATH")
    return [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.ports.client),
    ]


# Backward-compatible alias
build_client_args = build_frontend_args


def describe_args(args: list[str]) -> str:
    """Format an argv list for logging display."""
    return " ".join(args)