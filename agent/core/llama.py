"""Talking to llama-server's router about its models.

llama-server runs in router mode (`--models-dir`): one server process lists
every model under the models folder and runs each in a child process when it
is loaded. Per-model endpoints (`/props`, `/apply-template`, `/tokenize`,
chat) must name the model, in the body or as `?model=`; without it they fail
with "model name is missing from the request". `/health` is ok as soon as the
router listens, before any model is loaded, so readiness of a *model* is read
from `/models`, whose `status.value` is unloaded, loading, loaded or failed.
"""

from __future__ import annotations

import time
from typing import Any

import httpx


class ModelError(RuntimeError):
    """A model could not be found or loaded."""


def base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_router(url: str, timeout: float = 2.0) -> bool:
    """True when the server at `url` runs in router mode (`/props` role)."""
    try:
        return httpx.get(f"{url}/props", timeout=timeout).json().get("role") == "router"
    except Exception:  # noqa: BLE001
        return False


def list_models(url: str, timeout: float = 5.0) -> list[dict[str, Any]]:
    response = httpx.get(f"{url}/models", timeout=timeout)
    response.raise_for_status()
    return response.json().get("data") or []


def find(url: str, name: str) -> dict[str, Any] | None:
    return next((m for m in list_models(url) if m.get("id") == name or name in (m.get("aliases") or [])), None)


def status(model: dict[str, Any]) -> str:
    return str((model.get("status") or {}).get("value", "unknown"))


def files(model: dict[str, Any]) -> tuple[str | None, str | None]:
    """The GGUF and mmproj a model was (or will be) started with."""
    args = (model.get("status") or {}).get("args") or []
    pick = lambda flag: args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None  # noqa: E731
    return pick("--model"), pick("--mmproj")


def modalities(model: dict[str, Any]) -> dict[str, bool]:
    """What a model takes in, from its listing. Known before it is loaded."""
    inputs = set((model.get("architecture") or {}).get("input_modalities") or [])
    return {"vision": "image" in inputs, "audio": "audio" in inputs}


def load(url: str, name: str, *, timeout: float = 600.0, interval: float = 0.5) -> dict[str, Any]:
    """Load `name` and wait until it is ready. Returns its listing.

    Raises ModelError naming the models that do exist when `name` is not one
    of them, and when loading fails or takes longer than `timeout`.
    """
    model = find(url, name)
    if model is None:
        known = ", ".join(m.get("id", "?") for m in list_models(url)) or "none"
        raise ModelError(f"no model {name!r} in the models folder (found: {known})")
    if status(model) != "loaded":
        response = httpx.post(f"{url}/models/load", json={"model": name}, timeout=30)
        if response.status_code >= 400 and "already" not in response.text.lower():
            raise ModelError(f"llama-server would not load {name!r}: {response.text[:300]}")
    started = time.monotonic()
    while True:
        model = find(url, name) or {}
        state = status(model)
        if state == "loaded":
            return model
        # `unloaded` just after asking is a race; a few seconds on, it gave up.
        if state == "failed" or (state == "unloaded" and time.monotonic() - started > 5):
            raise ModelError(f"{name!r} failed to load; see llama-server's output above")
        if time.monotonic() - started > timeout:
            raise ModelError(f"{name!r} did not load within {timeout:.0f}s")
        time.sleep(interval)


__all__ = ["ModelError", "base_url", "files", "find", "is_router", "list_models", "load", "modalities", "status"]
