from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, computed_field
from pathlib import Path
from enum import Enum
import json
import base64
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# settings.json lives at the project root (two levels above server/routers/)
SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"

try:
    import win32crypt
    HAS_WIN32CRYPT = True
except ImportError:
    HAS_WIN32CRYPT = False


def encrypt_secret(plain_text: str) -> str:
    if not plain_text:
        return ""
    if plain_text.startswith("ENC:"):
        return plain_text
    if plain_text == "********":
        return plain_text
    if HAS_WIN32CRYPT:
        try:
            encrypted_bytes = win32crypt.CryptProtectData(
                plain_text.encode("utf-8"), None, None, None, None, 0
            )
            return "ENC:" + base64.b64encode(encrypted_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"win32crypt encryption failed: {e}")
    # Fallback if win32crypt is not available
    return "ENC:" + base64.b64encode(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    if not cipher_text.startswith("ENC:"):
        return cipher_text
    raw_payload = cipher_text[4:]
    if HAS_WIN32CRYPT:
        try:
            raw_bytes = base64.b64decode(raw_payload)
            _, decrypted_bytes = win32crypt.CryptUnprotectData(
                raw_bytes, None, None, None, 0
            )
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            logger.warning(f"win32crypt decryption failed: {e}")
    try:
        return base64.b64decode(raw_payload).decode("utf-8")
    except Exception:
        return cipher_text


# --- Enums & Provider Configuration ---

class CloudProvider(str, Enum):
    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


PROVIDER_BASE_URLS = {
    CloudProvider.GOOGLE: "https://generativelanguage.googleapis.com/v1beta/openai/",
    CloudProvider.OPENAI: "https://api.openai.com/v1/",
    CloudProvider.ANTHROPIC: "https://api.anthropic.com/v1/",
}


# --- Configuration Data Models ---

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

    @computed_field
    @property
    def base_url(self) -> str:
        return PROVIDER_BASE_URLS.get(self.provider, PROVIDER_BASE_URLS[CloudProvider.GOOGLE])


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


def _load_raw_dict() -> dict:
    if SETTINGS_PATH.is_file():
        try:
            return json.loads(SETTINGS_PATH.read_text("utf-8"))
        except Exception as e:
            logger.error(f"Error reading settings.json: {e}")
    return {}


def _prepare_response_settings(raw_data: dict, reveal: bool) -> Settings:
    try:
        settings_obj = Settings.model_validate(raw_data)
    except Exception:
        settings_obj = Settings()

    # Process Cloud API Key
    cloud_key = settings_obj.model.cloud.api_key
    if cloud_key:
        if reveal:
            settings_obj.model.cloud.api_key = decrypt_secret(cloud_key)
        else:
            settings_obj.model.cloud.api_key = "********"
    else:
        settings_obj.model.cloud.api_key = ""

    # Process Exa API Key
    exa_key = settings_obj.tools.exa.api_key
    if exa_key:
        if reveal:
            settings_obj.tools.exa.api_key = decrypt_secret(exa_key)
        else:
            settings_obj.tools.exa.api_key = "********"
    else:
        settings_obj.tools.exa.api_key = ""

    return settings_obj


def _save(settings_input: Settings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing_raw = _load_raw_dict()
    existing_cloud_key = (
        existing_raw.get("model", {})
        .get("cloud", {})
        .get("api_key", "")
    )
    existing_exa_key = (
        existing_raw.get("tools", {})
        .get("exa", {})
        .get("api_key", "")
    )

    data = settings_input.model_dump()

    # Handle Cloud API Key encryption / preservation
    new_cloud_key = data["model"]["cloud"]["api_key"]
    if new_cloud_key == "********":
        data["model"]["cloud"]["api_key"] = existing_cloud_key
    elif new_cloud_key and not new_cloud_key.startswith("ENC:"):
        data["model"]["cloud"]["api_key"] = encrypt_secret(new_cloud_key)

    # Handle Exa API Key encryption / preservation
    new_exa_key = data["tools"]["exa"]["api_key"]
    if new_exa_key == "********":
        data["tools"]["exa"]["api_key"] = existing_exa_key
    elif new_exa_key and not new_exa_key.startswith("ENC:"):
        data["tools"]["exa"]["api_key"] = encrypt_secret(new_exa_key)

    SETTINGS_PATH.write_text(json.dumps(data, indent=2), "utf-8")


@router.get("/settings", response_model=Settings, tags=["Settings"])
async def get_settings(reveal: bool = Query(False)):
    raw_data = _load_raw_dict()
    return _prepare_response_settings(raw_data, reveal=reveal)


@router.post("/settings", response_model=Settings, tags=["Settings"])
async def update_settings(settings: Settings, reveal: bool = Query(False)):
    _save(settings)
    raw_data = _load_raw_dict()
    return _prepare_response_settings(raw_data, reveal=reveal)
