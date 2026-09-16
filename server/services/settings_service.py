"""Authoritative settings loading, secret protection, and runtime resolution."""

import base64
import json
import logging
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"

try:
    import win32crypt
except ImportError:  # pragma: no cover - Windows deployment dependency
    win32crypt = None


class CloudProvider(str, Enum):
    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


PROVIDER_BASE_URLS = {
    CloudProvider.GOOGLE: "https://generativelanguage.googleapis.com/v1beta/openai/",
    CloudProvider.OPENAI: "https://api.openai.com/v1/",
    CloudProvider.ANTHROPIC: "https://api.anthropic.com/v1/",
}


class LocalModelConfig(BaseModel):
    name: str = "gemma-4-E2B_q4_0-it.gguf"
    base_url: str = "http://127.0.0.1:8000/v1"
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    context_window: int = 8192


class CloudModelConfig(BaseModel):
    provider: CloudProvider = CloudProvider.GOOGLE
    name: str = "gemini-3.5-flash-lite"
    api_key: str = ""
    base_url: str = PROVIDER_BASE_URLS[CloudProvider.GOOGLE]


class ModelSettings(BaseModel):
    local: LocalModelConfig = Field(default_factory=LocalModelConfig)
    cloud: CloudModelConfig = Field(default_factory=CloudModelConfig)


class AgentRuntimeSettings(BaseModel):
    default_mode: str = "local"
    max_tool_iterations: int = 5
    reflect_on_tool_use: bool = True
    system_prompt_extra: str = ""


class ExaToolConfig(BaseModel):
    api_key: str = ""
    max_results: int = 5


class ToolsSettings(BaseModel):
    exa: ExaToolConfig = Field(default_factory=ExaToolConfig)


class SystemSettings(BaseModel):
    download_directory: str = ""


class Settings(BaseModel):
    model: ModelSettings = Field(default_factory=ModelSettings)
    agent_runtime: AgentRuntimeSettings = Field(default_factory=AgentRuntimeSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    system: SystemSettings = Field(default_factory=SystemSettings)


def encrypt_secret(value: str) -> str:
    if not value or value.startswith("ENC:") or value == "********":
        return value
    if win32crypt is None:
        raise RuntimeError("DPAPI is unavailable; refusing to persist an unencrypted secret.")
    protected = win32crypt.CryptProtectData(value.encode("utf-8"), None, None, None, None, 0)
    return "ENC:" + base64.b64encode(protected).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value or not value.startswith("ENC:"):
        return value
    if win32crypt is None:
        logger.warning("DPAPI is unavailable; encrypted setting cannot be used.")
        return ""
    try:
        _, plain = win32crypt.CryptUnprotectData(base64.b64decode(value[4:]), None, None, None, 0)
        return plain.decode("utf-8")
    except Exception as exc:
        logger.warning("Unable to decrypt a DPAPI-protected setting: %s", exc)
        return ""


def _load_raw_dict() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.exception("Unable to read settings.json.")
        return {}


def get_effective_settings() -> Settings:
    """Return settings with secrets decrypted only in memory."""
    settings = Settings.model_validate(_load_raw_dict())
    settings.model.cloud.api_key = decrypt_secret(settings.model.cloud.api_key)
    settings.tools.exa.api_key = decrypt_secret(settings.tools.exa.api_key)
    return settings


def get_public_settings(*, reveal: bool = False) -> Settings:
    settings = Settings.model_validate(_load_raw_dict())
    for secret in (settings.model.cloud, settings.tools.exa):
        secret.api_key = decrypt_secret(secret.api_key) if reveal else ("********" if secret.api_key else "")
    return settings


def save_settings(settings: Settings) -> None:
    current = _load_raw_dict()
    data = settings.model_dump(mode="json")
    for path in (("model", "cloud", "api_key"), ("tools", "exa", "api_key")):
        source = current
        target = data
        for key in path[:-1]:
            source = source.get(key, {})
            target = target[key]
        key = path[-1]
        candidate = target[key]
        if candidate == "********":
            target[key] = source.get(key, "")
        elif candidate and not candidate.startswith("ENC:"):
            target[key] = encrypt_secret(candidate)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
