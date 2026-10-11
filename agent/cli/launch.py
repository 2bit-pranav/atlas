"""Building the llama-server command line from restart-tier settings.

Section 3: the CLI spawns llama-server "with restart-tier settings", so the
argv is derived from ``settings.json`` rather than hardcoded. Every flag Atlas
depends on is a setting; ``llamacpp.extra_args`` is the escape hatch for flags
this function does not model yet.

Kept pure and separate from the spawning code so it can be tested without
starting anything.
"""

from __future__ import annotations

import logging

from agent.cli.settings import Settings

logger = logging.getLogger(__name__)


def build_llamacpp_args(settings: Settings) -> list[str]:
    """Full argv for the llama-server process, including the binary name.

    Mirrors ``ext/start_gemma.bat`` in the sibling Atlas repo, which is the
    known-good local invocation::

        llama serve -m <gguf> --mmproj <mmproj> -ngl 99 -fa on -b 2048 -ub 512
                  -c 32768 -t 6 --jinja --reasoning auto --tools all

    Deliberate differences from that file:
      * ``--port`` and ``--host`` are explicit, so the port is a setting rather
        than an accident of the default (and we never bind 0.0.0.0);
      * ``-np 1``, because with N slots llama.cpp splits ``-c`` across them;
      * ``--tools`` is NOT enabled - see LlamaCppSettings.built_in_tools.
    """
    model = settings.model
    args: list[str] = [settings.llamacpp.binary]
    if settings.llamacpp.subcommand:
        args.append(settings.llamacpp.subcommand)

    args += ["-m", model.path]

    if model.mmproj_path:
        args += ["--mmproj", model.mmproj_path]

    args += ["-c", str(model.context_size)]

    # -ngl accepts a number, 'auto' or 'all'. 'auto' (the llama.cpp default)
    # offloads as much as fits and falls back to CPU when there is no GPU,
    # which is why it is the portable setting default rather than 0.
    gpu_layers = model.gpu_layers
    args += ["-ngl", str(gpu_layers) if isinstance(gpu_layers, int) else gpu_layers]

    if model.device and model.device != "auto":
        args += ["--device", model.device]

    args += ["-b", str(model.batch_size), "-ub", str(model.ubatch_size)]

    if model.threads:
        args += ["-t", str(model.threads)]

    # Loopback only: the server is a child process, not a network service.
    args += ["--host", "127.0.0.1", "--port", str(settings.ports.llama)]

    # S25: one run at a time means one slot, which keeps the whole context in
    # that slot. Emitted even when 1 so launched.json records a complete flag
    # list that reproduces this launch exactly.
    args += ["-np", str(model.parallel_slots)]

    args += ["-fa", "on" if model.flash_attention else "off"]

    if model.jinja:
        # Required: the Gemma chat template renders tool calls and thinking.
        args.append("--jinja")

    # `--reasoning` (not `--reasoning-format`): on/off/auto. With auto,
    # llama.cpp detects the deepseek thought format, which is what populates
    # message.reasoning_content and therefore what S2's passthrough reads.
    args += ["--reasoning", model.reasoning]

    if settings.llamacpp.built_in_tools:
        logger.warning(
            "llamacpp.built_in_tools is on: llama.cpp itself would offer the model "
            "exec_shell_command, read_file and write_file"
        )
        args += ["--tools", "all"]

    args += list(settings.llamacpp.extra_args)
    return args


def build_backend_args(settings: Settings) -> list[str]:
    """Argv for the FastAPI backend.

    Must start with the interpreter: the first element of a Popen argv is the
    executable, and ``-m`` on its own is not a program.
    """
    import sys

    return [
        sys.executable,
        "-m",
        "uvicorn",
        "agent.server.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(settings.ports.backend),
    ]


def describe_args(args: list[str]) -> str:
    """Single-line rendering for logs and for launched.json's flag list."""
    return " ".join(args)
