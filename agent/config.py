import os
from typing import Dict, Any
from dotenv import load_dotenv
from autogen_ext.models.openai import OpenAIChatCompletionClient, _openai_client
from autogen_core.models import AssistantMessage

load_dotenv()

# configure these params in .env
MODE: str = os.getenv("MODE", "true").lower()
USE_LOCAL_MODEL = True if MODE == "true" else False
LOCAL_MODEL_NAME: str = os.getenv("LOCAL_MODEL_NAME", "gemma-4-E2B_q4_0-it.gguf")
LOCAL_BASE_URL: str = os.getenv("LOCAL_BASE_URL", "http://127.0.0.1:8000/v1")
CLOUD_MODEL_NAME: str = os.getenv("CLOUD_MODEL_NAME", "gemini-2.0-flash")
CLOUD_BASE_URL: str = os.getenv("CLOUD_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
CLOUD_API_KEY: str = os.getenv("CLOUD_API_KEY", "")

# Cache to preserve Google Gemini thought_signatures across tool calling turns
THOUGHT_SIGNATURE_CACHE: Dict[str, Any] = {}

# Patch AutoGen 0.7.5 to_oai_type to re-inject thought_signatures into assistant tool_calls
_original_to_oai_type = _openai_client.to_oai_type


def _patched_to_oai_type(
    message, prepend_name=False, model="unknown", model_family="unknown", include_name_in_message=True
):
    res = _original_to_oai_type(
        message,
        prepend_name=prepend_name,
        model=model,
        model_family=model_family,
        include_name_in_message=include_name_in_message,
    )
    if isinstance(message, AssistantMessage) and isinstance(message.content, list):
        for msg_dict in res:
            if isinstance(msg_dict, dict) and msg_dict.get("role") == "assistant" and "tool_calls" in msg_dict:
                for tc in msg_dict["tool_calls"]:
                    if isinstance(tc, dict):
                        cid = tc.get("id")
                        if cid and cid in THOUGHT_SIGNATURE_CACHE:
                            tc["extra_content"] = THOUGHT_SIGNATURE_CACHE[cid]
                        elif "extra_content" not in tc:
                            tc["extra_content"] = {"google": {"thought_signature": "bypass"}}
    return res

_openai_client.to_oai_type = _patched_to_oai_type

def get_model_client(use_local: bool = USE_LOCAL_MODEL) -> OpenAIChatCompletionClient:
    """
    Constructs an AutoGen OpenAIChatCompletionClient for local or cloud model.
    """
    if use_local:
        model = LOCAL_MODEL_NAME
        base_url = LOCAL_BASE_URL
        api_key = "bypass"
    else:
        model = CLOUD_MODEL_NAME
        base_url = CLOUD_BASE_URL
        api_key = CLOUD_API_KEY

    # Ensure trailing slash on base_url
    if base_url and not base_url.endswith("/"):
        base_url = base_url + "/"

    model_info: Dict[str, Any] = {
        "vision": True,
        "function_calling": True,
        "structured_output": True,
        "json_output": True,
        "family": "unknown",
    }

    client = OpenAIChatCompletionClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        model_info=model_info,
        parallel_tool_calls=False,
    )

    # Intercept OpenAI chat completions creation to cache Google Gemini thought_signatures
    orig_oai_create = client._client.chat.completions.create

    async def wrapped_oai_create(*args, **kwargs):
        resp = await orig_oai_create(*args, **kwargs)
        if hasattr(resp, "choices") and resp.choices:
            msg = resp.choices[0].message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    extra = getattr(tc, "extra_content", None)
                    if extra:
                        THOUGHT_SIGNATURE_CACHE[tc.id] = extra
        return resp

    client._client.chat.completions.create = wrapped_oai_create
    return client
